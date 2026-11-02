import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { ChartOptionSwitch } from 'lib/components/ChartOptions/ChartOptionSwitch'
import { DisplayOptionBindings } from 'lib/components/ChartOptions/displayOptions'
import { LegendOption } from 'lib/components/ChartOptions/LegendOption'
import { MetricOptions } from 'lib/components/ChartOptions/MetricOptions'
import { PieTotalOption } from 'lib/components/ChartOptions/PieTotalOption'
import type { DisplayOptionsAdapter } from 'lib/components/ChartOptions/useDisplayOptions'
import { PART_OF_WHOLE_DISPLAY_TYPES, PIE_DISPLAY_TYPES } from 'lib/constants'

import { ChartDisplayType } from '~/types'

import { dataVisualizationLogic } from '../dataVisualizationLogic'
import { displayLogic, type displayLogicType } from '../displayLogic'
import { buildPieSlices, partOfWholeChartData, showsLegendByDefault, showsPieTotal } from './Charts/sqlPieGraphAdapter'
import { SQL_METRIC_SUMMARY_DEFAULT } from './Charts/useSqlMetricModel'
import { seriesBreakdownLogic } from './seriesBreakdownLogic'

interface SqlDisplayContext
    extends
        Pick<displayLogicType['values'], 'chartSettings'>,
        Pick<displayLogicType['actions'], 'updateChartSettings'> {
    isMetric: boolean
    isPieChart: boolean
    isDonutChart: boolean
    isProportionBar: boolean
    isPartOfWholeChart: boolean
    isStackedBarChart: boolean
    isBarChart: boolean
    isScatterPlot: boolean
    isBoxPlot: boolean
    isHorizontalBarChart: boolean
    isLineChart: boolean
    isSingleAxisChart: boolean
    isDateXAxis: boolean
    supportsAnnotations: boolean
    showsAxes: boolean
    showsSeriesOptions: boolean
    showsRightYAxis: boolean
    showLegend: boolean
}

function useSqlDisplayContext(): SqlDisplayContext {
    const { effectiveVisualizationType, xData, yData, dataVisualizationProps } = useValues(dataVisualizationLogic)
    const { seriesBreakdownData } = useValues(seriesBreakdownLogic({ key: dataVisualizationProps.key }))
    const { chartSettings } = useValues(displayLogic)
    const { updateChartSettings } = useActions(displayLogic)

    const type = effectiveVisualizationType
    const isMetric = type === ChartDisplayType.Metric
    const isProportionBar = type === ChartDisplayType.ActionsProportionBar
    const isPartOfWholeChart = PART_OF_WHOLE_DISPLAY_TYPES.includes(type)
    const isScatterPlot = type === ChartDisplayType.ScatterPlot
    const isBoxPlot = type === ChartDisplayType.BoxPlot
    const isHorizontalBarChart = type === ChartDisplayType.ActionsBarValue
    const isLineChart = type === ChartDisplayType.ActionsLineGraph || type === ChartDisplayType.ActionsAreaGraph
    // Scatter and box plots have a single Y axis, so there is no separate right axis to configure.
    const isSingleAxisChart = isScatterPlot || isBoxPlot
    const showsAxes = !isMetric && !isPartOfWholeChart
    const proportionBarPartCount = useMemo(() => {
        if (!isProportionBar) {
            return 0
        }
        const pieData = partOfWholeChartData(seriesBreakdownData, xData, yData)
        return buildPieSlices(pieData.xData, pieData.yData).length
    }, [isProportionBar, seriesBreakdownData, xData, yData])

    return {
        chartSettings,
        updateChartSettings,
        isMetric,
        isPieChart: PIE_DISPLAY_TYPES.includes(type),
        isDonutChart: type === ChartDisplayType.ActionsDonut,
        isProportionBar,
        isPartOfWholeChart,
        isStackedBarChart: type === ChartDisplayType.ActionsStackedBar,
        isBarChart: type === ChartDisplayType.ActionsBar,
        isScatterPlot,
        isBoxPlot,
        isHorizontalBarChart,
        isLineChart,
        isSingleAxisChart,
        isDateXAxis: xData?.column.type.name === 'DATE' || xData?.column.type.name === 'DATETIME',
        supportsAnnotations:
            isLineChart || type === ChartDisplayType.ActionsBar || type === ChartDisplayType.ActionsStackedBar,
        showsAxes,
        showsSeriesOptions: showsAxes && !isSingleAxisChart,
        showsRightYAxis: showsAxes && !isSingleAxisChart && !isHorizontalBarChart,
        showLegend: chartSettings.showLegend ?? showsLegendByDefault(isProportionBar, proportionBarPartCount),
    }
}

const SQL_BINDINGS: DisplayOptionBindings<SqlDisplayContext> = {
    metric: {
        showCondition: (c) => c.isMetric,
        render: (c) => (
            <MetricOptions
                settings={c.chartSettings.metric ?? {}}
                defaultSummary={SQL_METRIC_SUMMARY_DEFAULT}
                onChange={(metric) => c.updateChartSettings({ metric })}
                summaryDataAttr="data-visualization-metric-summary"
            />
        ),
    },
    valuesOnSeries: {
        showCondition: (c) => c.showsSeriesOptions,
        value: (c) => c.chartSettings.showValuesOnSeries ?? false,
        onChange: (showValuesOnSeries, c) => c.updateChartSettings({ showValuesOnSeries }),
    },
    valueLabelPosition: {
        showCondition: (c) => c.showsSeriesOptions && !!c.chartSettings.showValuesOnSeries && !c.isLineChart,
        value: (c) => c.chartSettings.valueLabelPosition ?? 'end',
        onChange: (valueLabelPosition, c) => c.updateChartSettings({ valueLabelPosition }),
    },
    valueLabelBackground: {
        showCondition: (c) => c.showsSeriesOptions && !!c.chartSettings.showValuesOnSeries,
        value: (c) => c.chartSettings.valueLabelBackground ?? true,
        onChange: (valueLabelBackground, c) => c.updateChartSettings({ valueLabelBackground }),
    },
    valueLabelFontSize: {
        showCondition: (c) => c.showsSeriesOptions && !!c.chartSettings.showValuesOnSeries,
        value: (c) => c.chartSettings.valueLabelFontSize ?? 12,
        onChange: (valueLabelFontSize, c) => c.updateChartSettings({ valueLabelFontSize }),
    },
    valueLabelRotation: {
        showCondition: (c) => c.showsSeriesOptions && !!c.chartSettings.showValuesOnSeries,
        value: (c) => c.chartSettings.valueLabelRotation ?? 0,
        onChange: (valueLabelRotation, c) => c.updateChartSettings({ valueLabelRotation }),
    },
    percentStack: {
        showCondition: (c) => c.isStackedBarChart,
        value: (c) => c.chartSettings.stackBars100 ?? false,
        onChange: (stackBars100, c) => c.updateChartSettings({ stackBars100 }),
    },
    pieSliceContent: {
        showCondition: (c) => c.isPieChart,
        value: (c) => c.chartSettings.pie?.sliceContent ?? 'values',
        onChange: (sliceContent, c) => c.updateChartSettings({ pie: { sliceContent } }),
    },
    pieValueDisplay: {
        showCondition: (c) => c.isPieChart,
        value: (c) => c.chartSettings.pie?.valueDisplay ?? 'absolute',
        onChange: (valueDisplay, c) => c.updateChartSettings({ pie: { valueDisplay } }),
    },
    pieTotal: {
        showCondition: (c) => c.isPartOfWholeChart,
        render: (c) => (
            <PieTotalOption
                isDonut={c.isDonutChart}
                checked={showsPieTotal(c.chartSettings, c.isProportionBar)}
                onChange={(showTotal) => c.updateChartSettings({ pie: { showTotal } })}
            />
        ),
    },
    showTotalRow: {
        showCondition: (c) => c.showsSeriesOptions,
        value: (c) => c.chartSettings.showTotalRow ?? true,
        onChange: (showTotalRow, c) => c.updateChartSettings({ showTotalRow }),
    },
    showNullsAsZero: {
        showCondition: (c) => c.showsSeriesOptions,
        value: (c) => c.chartSettings.showNullsAsZero ?? false,
        onChange: (showNullsAsZero, c) => c.updateChartSettings({ showNullsAsZero }),
    },
    barSpacing: {
        showCondition: (c) => c.isStackedBarChart || c.isHorizontalBarChart || c.isBarChart,
        value: (c) => c.chartSettings.barGap ?? 0.2,
        onChange: (barGap, c) => c.updateChartSettings({ barGap }),
    },
    legend: {
        showCondition: (c) => !c.isMetric,
        render: (c) => (
            <LegendOption
                showLegend={c.showLegend}
                onShowLegendChange={(showLegend) => c.updateChartSettings({ showLegend })}
                position={
                    c.chartSettings.legendPosition ?? (c.isProportionBar ? 'bottom' : c.isPieChart ? 'right' : 'top')
                }
                onPositionChange={(legendPosition) => c.updateChartSettings({ legendPosition })}
            />
        ),
    },
    excludeOutliers: {
        showCondition: (c) => c.isBoxPlot,
        value: (c) => c.chartSettings.boxPlot?.excludeOutliers !== false,
        onChange: (excludeOutliers, c) => c.updateChartSettings({ boxPlot: { excludeOutliers } }),
    },
    annotations: {
        showCondition: (c) => c.supportsAnnotations,
        render: (c) => (
            <ChartOptionSwitch
                label="Show annotations"
                data-attr="data-visualization-show-annotations"
                disabledReason={!c.isDateXAxis ? 'Annotations need a Date or DateTime column on the X-axis' : undefined}
                checked={c.isDateXAxis && (c.chartSettings.showAnnotations ?? false)}
                onChange={(showAnnotations) => c.updateChartSettings({ showAnnotations })}
            />
        ),
    },

    xAxisLabel: {
        showCondition: (c) => c.showsAxes,
        value: (c) => c.chartSettings.xAxisLabel,
        onChange: (xAxisLabel, c) => c.updateChartSettings({ xAxisLabel }),
        placeholder: (c) => `${c.isHorizontalBarChart ? 'Y-axis' : 'X-axis'} label`,
        dataAttr: 'data-visualization-x-axis-label-input',
    },
    xAxisScale: {
        showCondition: (c) => c.showsAxes && c.isScatterPlot,
        value: (c) => (c.chartSettings.scatter?.xScale === 'logarithmic' ? 'log' : 'linear'),
        onChange: (scale, c) =>
            c.updateChartSettings({ scatter: { xScale: scale === 'log' ? 'logarithmic' : 'linear' } }),
    },
    xAxisBeginAtZero: {
        showCondition: (c) => c.showsAxes && c.isScatterPlot,
        value: (c) => c.chartSettings.scatter?.xStartAtZero ?? false,
        onChange: (xStartAtZero, c) => c.updateChartSettings({ scatter: { xStartAtZero } }),
    },
    xAxisDateFormat: {
        showCondition: (c) => c.showsAxes && c.isDateXAxis,
        value: (c) => c.chartSettings.xAxisDateFormat,
        onChange: (xAxisDateFormat, c) => c.updateChartSettings({ xAxisDateFormat }),
        dataAttr: 'chart-date-format',
    },
    xAxisTickRotation: {
        showCondition: (c) => c.showsSeriesOptions,
        value: (c) => c.chartSettings.xAxisTickRotation ?? 'auto',
        onChange: (rotation, c) =>
            c.updateChartSettings({ xAxisTickRotation: rotation === 'auto' ? undefined : rotation }),
    },
    xAxisShowTicks: {
        showCondition: (c) => c.showsAxes,
        value: (c) => c.chartSettings.showXAxisTicks ?? true,
        onChange: (showXAxisTicks, c) => c.updateChartSettings({ showXAxisTicks }),
    },
    // Quill's scatter draws both axis lines together, so a per-edge toggle can't be honored there.
    xAxisBorder: {
        showCondition: (c) => c.showsAxes && !c.isScatterPlot,
        value: (c) => c.chartSettings.showXAxisBorder ?? true,
        onChange: (showXAxisBorder, c) => c.updateChartSettings({ showXAxisBorder }),
    },

    yAxisLabel: {
        showCondition: (c) => c.showsAxes,
        value: (c) => c.chartSettings.leftYAxisSettings?.label,
        onChange: (label, c) => c.updateChartSettings({ leftYAxisSettings: { label } }),
        placeholder: (c) =>
            c.isHorizontalBarChart ? 'X-axis label' : c.showsRightYAxis ? 'Left Y-axis label' : 'Y-axis label',
        dataAttr: 'data-visualization-left-y-axis-label-input',
    },
    yAxisBeginAtZero: {
        showCondition: (c) => c.showsAxes && !c.isBoxPlot,
        value: (c) =>
            c.chartSettings.leftYAxisSettings?.startAtZero ??
            (c.isScatterPlot ? false : (c.chartSettings.yAxisAtZero ?? true)),
        onChange: (startAtZero, c) => c.updateChartSettings({ leftYAxisSettings: { startAtZero } }),
    },
    yAxisShowTicks: {
        showCondition: (c) => c.showsAxes,
        value: (c) => c.chartSettings.leftYAxisSettings?.showTicks ?? true,
        onChange: (showTicks, c) => c.updateChartSettings({ leftYAxisSettings: { showTicks } }),
    },
    yAxisGridLines: {
        showCondition: (c) => c.showsAxes,
        value: (c) => c.chartSettings.leftYAxisSettings?.showGridLines ?? true,
        onChange: (showGridLines, c) => c.updateChartSettings({ leftYAxisSettings: { showGridLines } }),
    },
    yAxisBorder: {
        showCondition: (c) => c.showsAxes && !c.isScatterPlot,
        value: (c) => c.chartSettings.showYAxisBorder ?? true,
        onChange: (showYAxisBorder, c) => c.updateChartSettings({ showYAxisBorder }),
    },
    yAxisScale: {
        showCondition: (c) => c.showsAxes,
        value: (c) => (c.chartSettings.leftYAxisSettings?.scale === 'logarithmic' ? 'log' : 'linear'),
        onChange: (scale, c) =>
            c.updateChartSettings({ leftYAxisSettings: { scale: scale === 'log' ? 'logarithmic' : 'linear' } }),
    },

    rightYAxisLabel: {
        showCondition: (c) => c.showsRightYAxis,
        value: (c) => c.chartSettings.rightYAxisSettings?.label,
        onChange: (label, c) => c.updateChartSettings({ rightYAxisSettings: { label } }),
        placeholder: () => 'Right Y-axis label',
        dataAttr: 'data-visualization-right-y-axis-label-input',
    },
    rightYAxisBeginAtZero: {
        showCondition: (c) => c.showsRightYAxis,
        value: (c) => c.chartSettings.rightYAxisSettings?.startAtZero ?? c.chartSettings.yAxisAtZero ?? true,
        onChange: (startAtZero, c) => c.updateChartSettings({ rightYAxisSettings: { startAtZero } }),
    },
    rightYAxisShowTicks: {
        showCondition: (c) => c.showsRightYAxis,
        value: (c) => c.chartSettings.rightYAxisSettings?.showTicks ?? true,
        onChange: (showTicks, c) => c.updateChartSettings({ rightYAxisSettings: { showTicks } }),
    },
    rightYAxisGridLines: {
        showCondition: (c) => c.showsRightYAxis,
        value: (c) => c.chartSettings.rightYAxisSettings?.showGridLines ?? true,
        onChange: (showGridLines, c) => c.updateChartSettings({ rightYAxisSettings: { showGridLines } }),
    },
    rightYAxisScale: {
        showCondition: (c) => c.showsRightYAxis,
        value: (c) => (c.chartSettings.rightYAxisSettings?.scale === 'logarithmic' ? 'log' : 'linear'),
        onChange: (scale, c) =>
            c.updateChartSettings({ rightYAxisSettings: { scale: scale === 'log' ? 'logarithmic' : 'linear' } }),
    },

    lineStyle: {
        showCondition: (c) => c.isLineChart,
        value: (c) => c.chartSettings.chartStyle?.curve ?? 'smooth',
        onChange: (curve, c) => c.updateChartSettings({ chartStyle: { curve } }),
        dataAttr: 'data-visualization-line-style',
    },
    trendLines: {
        showCondition: (c) => c.isScatterPlot,
        value: (c) => c.chartSettings.scatter?.showBestFit ?? false,
        onChange: (showBestFit, c) => c.updateChartSettings({ scatter: { showBestFit } }),
    },
}

// The SQL editor's Display tab and the options menu on a dashboard tile for a SQL chart.
export const sqlDisplayOptions: DisplayOptionsAdapter<SqlDisplayContext> = {
    useDisplayContext: useSqlDisplayContext,
    bindings: SQL_BINDINGS,
    settings: (c) => {
        // The horizontal bar chart swaps its axes, so the category axis is the Y-axis there.
        const categoryAxisName = c.isHorizontalBarChart ? 'Y-axis' : 'X-axis'
        const valueAxisName = c.isHorizontalBarChart ? 'X-axis' : 'Y-axis'
        return {
            groups: {
                'x-axis': { title: categoryAxisName },
                'y-axis': { title: c.showsRightYAxis ? `Left ${valueAxisName}` : valueAxisName },
                'right-y-axis': { title: `Right ${valueAxisName}` },
                annotations: { tooltip: null },
            },
        }
    },
}
