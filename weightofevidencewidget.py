# -*- coding: utf-8 -*-

#******************************************************************************
#
# MOLUSCE
# ---------------------------------------------------------
# Modules for Land Use Change Simulations
#
# Copyright (C) 2012-2013 NextGIS (info@nextgis.org)
#
# This source is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 2 of the License, or (at your option)
# any later version.
#
# This code is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# A copy of the GNU General Public License is available on the World Wide Web
# at <http://www.gnu.org/licenses/>. You can also obtain it by writing
# to the Free Software Foundation, 51 Franklin Street, Suite 500 Boston,
# MA 02110-1335 USA.
#
#******************************************************************************

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from qgis.core import *

from algorithms.models.area_analysis.manager import AreaAnalyst
from algorithms.models.woe.manager import WoeManager, WoeManagerError
from algorithms import dataprovider

import spinboxdelegate

from ui.ui_weightofevidencewidgetbase import Ui_Widget

import molusceutils as utils

class WeightOfEvidenceWidget(QWidget, Ui_Widget):
  def __init__(self, plugin, parent=None):
    QWidget.__init__(self, parent)
    self.setupUi(self)

    self.plugin = plugin
    self.inputs = plugin.inputs

    self.settings = QSettings("NextGIS", "MOLUSCE")

    self.btnTrainModel.clicked.connect(self.trainModel)

    self.btnResetBins.clicked.connect(self.__resetBins)

    self.manageGui()

  def manageGui(self):
    if not utils.checkFactors(self.inputs):
      QMessageBox.warning(self.plugin,
                          self.tr("Missed input data"),
                          self.tr("Factors rasters is not set. Please specify them and try again")
                         )
      return

    self.tblReclass.clearContents()
    self.delegate = spinboxdelegate.SpinBoxDelegate(self.tblReclass.model(), minRange=2, maxRange=dataprovider.MAX_CATEGORIES)

    row = 0
    for k, v in self.inputs["factors"].iteritems():
      v.denormalize()   # Denormalize the factor's bands if they are normalized
      for b in xrange(1, v.getBandsCount()+1):
        if v.isCountinues(b):
          self.tblReclass.insertRow(row)
          if v.getBandsCount()>1:
            name = u"%s (band %s)" % (utils.getLayerById(k).name(), unicode(b))
          else:
            name = u"%s" % (utils.getLayerById(k).name(), )
          stat = v.getBandStat(b)
          for n, item_data in enumerate([name, (u"%f" % (stat["min"], )), (u"%f" % (stat["max"])), u"" , u"" ]):
            item = QTableWidgetItem(item_data)
            if n < 3:
              item.setFlags(item.flags() ^ Qt.ItemIsEditable)
            self.tblReclass.setItem(row, n, item)
          row += 1
    rowCount = row

    self.tblReclass.setItemDelegateForColumn(3, self.delegate)
    for row in range(rowCount):
      # Set 2 bins as default value
      self.tblReclass.setItem(row, 3, QTableWidgetItem(u'2'))

    self.tblReclass.resizeRowsToContents()
    self.tblReclass.resizeColumnsToContents()

  def trainModel(self):
    if not utils.checkInputRasters(self.inputs):
      QMessageBox.warning(self.plugin,
                          self.tr("Missed input data"),
                          self.tr("Initial or final raster is not set. Please specify input data and try again")
                         )
      return

    if not utils.checkFactors(self.inputs):
      QMessageBox.warning(self.plugin,
                          self.tr("Missed input data"),
                          self.tr("Factors rasters is not set. Please specify them and try again")
                         )
      return

    self.plugin.logMessage(self.tr("Init AreaAnalyst"))
    analyst = AreaAnalyst(self.inputs["initial"], self.inputs["final"])

    myBins = self.__getBins()

    self.plugin.logMessage(self.tr("Init WoE model"))
    try:
      self.model = WoeManager(self.inputs["factors"].values(), analyst, bins=myBins)
    except WoeManagerError as err:
      QMessageBox.warning(self.plugin,
                          self.tr("Initialization error"),
                          err.msg
                         )
      return

    if not self.model.checkBins():
      QMessageBox.warning(self.plugin,
                          self.tr("Wrong binning"),
                          self.tr("Bins are not correctly specifed. Please specify them and try again")
                         )
      return

    self.model.moveToThread(self.plugin.workThread)
    self.plugin.workThread.started.connect(self.model.train)
    self.model.updateProgress.connect(self.plugin.showProgress)
    self.model.rangeChanged.connect(self.plugin.setProgressRange)
    self.model.processFinished.connect(self.__trainFinished)
    self.model.processFinished.connect(self.plugin.workThread.quit)

    self.plugin.workThread.start()
    self.inputs["model"] = self.model

  def __trainFinished(self):
    self.plugin.workThread.started.disconnect(self.model.train)
    self.model.updateProgress.disconnect(self.plugin.showProgress)
    self.model.rangeChanged.connect(self.plugin.setProgressRange)
    self.model.processFinished.disconnect(self.__trainFinished)
    self.model.processFinished.disconnect(self.plugin.workThread.quit)
    self.plugin.restoreProgressState()
    self.plugin.logMessage(self.tr("WoE model trained"))
    self.pteWeightsInform.appendPlainText( unicode(self.model.weightsToText()) )

  def __getBins(self):
    bins = dict()
    n = 0
    for k, v in self.inputs["factors"].iteritems():
      lst = []
      for b in xrange(v.getBandsCount()):
        lst.append(None)
        if v.isCountinues(b+1):
          if v.getBandsCount()>1:
            name = u"%s (band %s)" % (utils.getLayerById(k).name(), unicode(b+1))
          else:
            name = u"%s" % (utils.getLayerById(k).name(), )
          items = self.tblReclass.findItems(name, Qt.MatchExactly)
          idx = self.tblReclass.indexFromItem(items[0])
          reclassList = self.tblReclass.item(idx.row(), 4).text()
          try:
            lst[b] = [int(j) for j in reclassList.split(" ")]
          except ValueError:
            QMessageBox.warning(self.plugin,
                          self.tr("Wrong binning"),
                          self.tr("Bins are not correctly specifed. Please specify them and try again (use space as separator)")
                         )
            return {}
      bins[n] = lst
      n += 1

    return bins

  def __resetBins(self):
    for row in xrange(self.tblReclass.rowCount()):
      try:
        rangeMin = float(self.tblReclass.item(row, 1).text())
        rangeMax = float(self.tblReclass.item(row, 2).text())
        intervals = int(float(self.tblReclass.item(row, 3).text()))
      except ValueError:
        continue
      delta = (rangeMax - rangeMin)/intervals
      item = [unicode( int(rangeMin + delta*(i)) )  for i in range(1,intervals)]
      item = u" ".join(item)
      item = QTableWidgetItem(item)
      self.tblReclass.setItem(row, 4, item)
