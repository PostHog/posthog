import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { AxisLabelOption } from 'lib/components/ChartOptions/AxisLabelOption'
import { AxisScaleOption } from 'lib/components/ChartOptions/AxisScaleOption'
import { BeginAtZeroOption } from 'lib/components/ChartOptions/BeginAtZeroOption'
import { ChartOptionSelect } from 'lib/components/ChartOptions/ChartOptionSelect'
import { ChartOptionSwitch } from 'lib/components/ChartOptions/ChartOptionSwitch'
import { ChartOptionTextInput } from 'lib/components/ChartOptions/ChartOptionTextInput'
import { ChartOptionToggleGroup } from 'lib/components/ChartOptions/ChartOptionToggleGroup'
import { DisplayOptionTab, groupDisplayOptions } from 'lib/components/ChartOptions/displayOptionLayout'
import { ExcludeOutliersOption } from 'lib/components/ChartOptions/ExcludeOutliersOption'
import { LegendOption } from 'lib/components/ChartOptions/LegendOption'
import { LineStyleOption } from 'lib/components/ChartOptions/LineStyleOption'
import { MetricOptions } from 'lib/components/ChartOptions/MetricOptions'
import { PercentOfTotalOption } from 'lib/components/ChartOptions/PercentOfTotalOption'
import { PieTotalOption } from 'lib/components/ChartOptions/PieTotalOption'
import { ValuesOnSeriesOption } from 'lib/components/ChartOptions/ValuesOnSeriesOption'
import { PART_OF_WHOLE_DISPLAY_TYPES, PIE_DISPLAY_TYPES } from 'lib/constants'

import { ChartDisplayType } from '~/types'

import { dataVisualizationLogic } from '../dataVisualizationLogic'
import { displayLogic } from '../displayLogic'
import { buildPieSlices, partOfWholeChartData, showsLegendByDefault, showsPieTotal } from './Charts/sqlPieGraphAdapter'
import { SQL_METRIC_SUMMARY_DEFAULT } from './Charts/useSqlMetricModel'
import { seriesBreakdownLogic } from './seriesBreakdownLogic'

const PIE_SLICE_CONTENT_OPTIONS: { value: 'labels' | 'values' | 'none'; label: string }[] = [
    { value: 'labels', label: 'Labels' },
    { value: 'values', label: 'Values' },
    { value: 'none', label: 'Nothing' },
]

const PIE_VALUE_DISPLAY_OPTIONS: { value: 'absolute' | 'percentage'; label: string }[] = [
    { value: 'absolute', label: 'Absolute' },
    { value: 'percentage', label: 'Percentage' },
]

const VALUE_POSITION_OPTIONS: { value: 'end' | 'center'; label: string }[] = [
    { value: 'end', label: 'At the end' },
    { value: 'center', label: 'Inside' },
]

const FONT_SIZE_OPTIONS = [8, 10, 12, 14, 16, 20, 24, 32].map((value) => ({ value, label: `${value}px` }))

const ROTATION_OPTIONS = [0, -45, -90, 45, 90].map((value) => ({ value, label: `${value}°` }))

// A select value can't be null, so "Automatic" stands in for an unset rotation.
const TICK_ROTATION_OPTIONS: { value: number | 'auto'; label: string }[] = [
    { value: 'auto', label: 'Automatic' },
    ...ROTATION_OPTIONS,
]

const BAR_GAP_OPTIONS = [
    { value: 0, label: 'None' },
    { value: 0.1, label: 'Small' },
    { value: 0.2, label: 'Medium' },
    { value: 0.4, label: 'Large' },
]

type YAxisSettingsName = 'leftYAxisSettings' | 'rightYAxisSettings'

export function useSqlDisplayOptions(): { tabs: DisplayOptionTab[] } {
    const { effectiveVisualizationType, xData, yData, dataVisualizationProps } = useValues(dataVisualizationLogic)
    const { seriesBreakdownData } = useValues(seriesBreakdownLogic({ key: dataVisualizationProps.key }))
    const { chartSettings } = useValues(displayLogic)
    const { updateChartSettings } = useActions(displayLogic)

    const isMetric = effectiveVisualizationType === ChartDisplayType.Metric
    const isStackedBarChart = effectiveVisualizationType === ChartDisplayType.ActionsStackedBar
    const isPieChart = PIE_DISPLAY_TYPES.includes(effectiveVisualizationType)
    const isDonutChart = effectiveVisualizationType === ChartDisplayType.ActionsDonut
    const isProportionBar = effectiveVisualizationType === ChartDisplayType.ActionsProportionBar
    const isPartOfWholeChart = PART_OF_WHOLE_DISPLAY_TYPES.includes(effectiveVisualizationType)
    const proportionBarPartCount = useMemo(() => {
        if (!isProportionBar) {
            return 0
        }
        const pieData = partOfWholeChartData(seriesBreakdownData, xData, yData)
        return buildPieSlices(pieData.xData, pieData.yData).length
    }, [isProportionBar, seriesBreakdownData, xData, yData])
    const showLegend = chartSettings.showLegend ?? showsLegendByDefault(isProportionBar, proportionBarPartCount)
    const isScatterPlot = effectiveVisualizationType === ChartDisplayType.ScatterPlot
    const isBoxPlot = effectiveVisualizationType === ChartDisplayType.BoxPlot
    const isHorizontalBarChart = effectiveVisualizationType === ChartDisplayType.ActionsBarValue
    // Scatter and box plots have a single Y axis, so there is no separate right axis to configure.
    const isSingleAxisChart = isScatterPlot || isBoxPlot
    const supportsRightYAxis = !isSingleAxisChart && !isHorizontalBarChart
    const isLineChart =
        effectiveVisualizationType === ChartDisplayType.ActionsLineGraph ||
        effectiveVisualizationType === ChartDisplayType.ActionsAreaGraph
    const isDateXAxis = xData?.column.type.name === 'DATE' || xData?.column.type.name === 'DATETIME'
    const supportsAnnotations =
        isLineChart ||
        effectiveVisualizationType === ChartDisplayType.ActionsBar ||
        effectiveVisualizationType === ChartDisplayType.ActionsStackedBar
    const showsAxes = !isMetric && !isPartOfWholeChart
    const showsSeriesOptions = showsAxes && !isSingleAxisChart
    const showsValueLabelOptions = showsSeriesOptions && !!chartSettings.showValuesOnSeries

    // The horizontal bar chart swaps its axes, so the category axis is the Y-axis there.
    const categoryAxisName = isHorizontalBarChart ? 'Y-axis' : 'X-axis'
    const valueAxisName = isHorizontalBarChart ? 'X-axis' : 'Y-axis'

    const yAxisOptions = (
        name: YAxisSettingsName
    ): {
        label: JSX.Element
        beginAtZero: JSX.Element
        showTicks: JSX.Element
        gridLines: JSX.Element
        scale: JSX.Element
    } => {
        const leftPlaceholder = isHorizontalBarChart
            ? 'X-axis label'
            : supportsRightYAxis
              ? 'Left Y-axis label'
              : 'Y-axis label'
        return {
            label: (
                <AxisLabelOption
                    data-attr={`data-visualization-${name === 'leftYAxisSettings' ? 'left' : 'right'}-y-axis-label-input`}
                    value={chartSettings[name]?.label}
                    placeholder={name === 'leftYAxisSettings' ? leftPlaceholder : 'Right Y-axis label'}
                    onChange={(label) => updateChartSettings({ [name]: { label } })}
                />
            ),
            beginAtZero: (
                <BeginAtZeroOption
                    checked={
                        chartSettings[name]?.startAtZero ??
                        (isScatterPlot ? false : (chartSettings.yAxisAtZero ?? true))
                    }
                    onChange={(startAtZero) => updateChartSettings({ [name]: { startAtZero } })}
                />
            ),
            showTicks: (
                <ChartOptionSwitch
                    label="Show tick labels"
                    checked={chartSettings[name]?.showTicks ?? true}
                    onChange={(showTicks) => updateChartSettings({ [name]: { showTicks } })}
                />
            ),
            gridLines: (
                <ChartOptionSwitch
                    label="Show grid lines"
                    checked={chartSettings[name]?.showGridLines ?? true}
                    onChange={(showGridLines) => updateChartSettings({ [name]: { showGridLines } })}
                />
            ),
            scale: (
                <AxisScaleOption
                    label="Scale"
                    value={chartSettings[name]?.scale === 'logarithmic' ? 'log' : 'linear'}
                    onChange={(scale) =>
                        updateChartSettings({ [name]: { scale: scale === 'log' ? 'logarithmic' : 'linear' } })
                    }
                />
            ),
        }
    }
    const leftYAxis = yAxisOptions('leftYAxisSettings')
    const rightYAxis = yAxisOptions('rightYAxisSettings')
    const showsRightYAxis = showsAxes && supportsRightYAxis

    return groupDisplayOptions(
        {
            metric: isMetric && {
                element: (
                    <MetricOptions
                        settings={chartSettings.metric ?? {}}
                        defaultSummary={SQL_METRIC_SUMMARY_DEFAULT}
                        onChange={(metric) => updateChartSettings({ metric })}
                        summaryDataAttr="data-visualization-metric-summary"
                    />
                ),
            },
            valuesOnSeries: showsSeriesOptions && {
                element: (
                    <ValuesOnSeriesOption
                        checked={chartSettings.showValuesOnSeries ?? false}
                        onChange={(showValuesOnSeries) => updateChartSettings({ showValuesOnSeries })}
                    />
                ),
            },
            valueLabelPosition: showsValueLabelOptions &&
                !isLineChart && {
                    element: (
                        <ChartOptionSelect
                            label="Value position"
                            value={chartSettings.valueLabelPosition ?? 'end'}
                            options={VALUE_POSITION_OPTIONS}
                            onChange={(valueLabelPosition) => updateChartSettings({ valueLabelPosition })}
                        />
                    ),
                },
            valueLabelBackground: showsValueLabelOptions && {
                element: (
                    <ChartOptionSwitch
                        label="Value background"
                        checked={chartSettings.valueLabelBackground ?? true}
                        onChange={(valueLabelBackground) => updateChartSettings({ valueLabelBackground })}
                    />
                ),
            },
            valueLabelFontSize: showsValueLabelOptions && {
                element: (
                    <ChartOptionSelect
                        label="Value font size"
                        value={chartSettings.valueLabelFontSize ?? 12}
                        options={FONT_SIZE_OPTIONS}
                        onChange={(valueLabelFontSize) => updateChartSettings({ valueLabelFontSize })}
                    />
                ),
            },
            valueLabelRotation: showsValueLabelOptions && {
                element: (
                    <ChartOptionSelect
                        label="Value rotation"
                        value={chartSettings.valueLabelRotation ?? 0}
                        options={ROTATION_OPTIONS}
                        onChange={(valueLabelRotation) => updateChartSettings({ valueLabelRotation })}
                    />
                ),
            },
            percentStack: isStackedBarChart && {
                element: (
                    <PercentOfTotalOption
                        checked={chartSettings.stackBars100 ?? false}
                        onChange={(stackBars100) => updateChartSettings({ stackBars100 })}
                    />
                ),
            },
            pieSliceContent: isPieChart && {
                element: (
                    <ChartOptionToggleGroup
                        label="Show on slices"
                        value={chartSettings.pie?.sliceContent ?? 'values'}
                        options={PIE_SLICE_CONTENT_OPTIONS}
                        onChange={(sliceContent) => updateChartSettings({ pie: { sliceContent } })}
                    />
                ),
            },
            pieValueDisplay: isPieChart && {
                element: (
                    <ChartOptionToggleGroup
                        label="Show values as"
                        value={chartSettings.pie?.valueDisplay ?? 'absolute'}
                        options={PIE_VALUE_DISPLAY_OPTIONS}
                        onChange={(valueDisplay) => updateChartSettings({ pie: { valueDisplay } })}
                    />
                ),
            },
            pieTotal: isPartOfWholeChart && {
                element: (
                    <PieTotalOption
                        isDonut={isDonutChart}
                        checked={showsPieTotal(chartSettings, isProportionBar)}
                        onChange={(showTotal) => updateChartSettings({ pie: { showTotal } })}
                    />
                ),
            },
            showTotalRow: showsSeriesOptions && {
                element: (
                    <ChartOptionSwitch
                        label="Show total row"
                        checked={chartSettings.showTotalRow ?? true}
                        onChange={(showTotalRow) => updateChartSettings({ showTotalRow })}
                    />
                ),
            },
            showNullsAsZero: showsSeriesOptions && {
                element: (
                    <ChartOptionSwitch
                        label="Show nulls as zero"
                        checked={chartSettings.showNullsAsZero ?? false}
                        onChange={(showNullsAsZero) => updateChartSettings({ showNullsAsZero })}
                    />
                ),
            },
            barSpacing: (isStackedBarChart ||
                isHorizontalBarChart ||
                effectiveVisualizationType === ChartDisplayType.ActionsBar) && {
                element: (
                    <ChartOptionSelect
                        label="Bar spacing"
                        value={chartSettings.barGap ?? 0.2}
                        options={BAR_GAP_OPTIONS}
                        onChange={(barGap) => updateChartSettings({ barGap })}
                    />
                ),
            },
            legend: !isMetric && {
                element: (
                    <LegendOption
                        showLegend={showLegend}
                        onShowLegendChange={(value) => updateChartSettings({ showLegend: value })}
                        position={
                            chartSettings.legendPosition ?? (isProportionBar ? 'bottom' : isPieChart ? 'right' : 'top')
                        }
                        onPositionChange={(legendPosition) => updateChartSettings({ legendPosition })}
                    />
                ),
            },
            excludeOutliers: isBoxPlot && {
                element: (
                    <ExcludeOutliersOption
                        checked={chartSettings.boxPlot?.excludeOutliers !== false}
                        onChange={(excludeOutliers) => updateChartSettings({ boxPlot: { excludeOutliers } })}
                    />
                ),
            },
            annotations: supportsAnnotations && {
                element: (
                    <ChartOptionSwitch
                        label="Show annotations"
                        data-attr="data-visualization-show-annotations"
                        disabledReason={
                            !isDateXAxis ? 'Annotations need a Date or DateTime column on the X-axis' : undefined
                        }
                        checked={isDateXAxis && (chartSettings.showAnnotations ?? false)}
                        onChange={(showAnnotations) => updateChartSettings({ showAnnotations })}
                    />
                ),
            },

            xAxisLabel: showsAxes && {
                element: (
                    <AxisLabelOption
                        data-attr="data-visualization-x-axis-label-input"
                        value={chartSettings.xAxisLabel}
                        placeholder={`${categoryAxisName} label`}
                        onChange={(xAxisLabel) => updateChartSettings({ xAxisLabel })}
                    />
                ),
            },
            xAxisScale: showsAxes &&
                isScatterPlot && {
                    element: (
                        <AxisScaleOption
                            label="Scale"
                            value={chartSettings.scatter?.xScale === 'logarithmic' ? 'log' : 'linear'}
                            onChange={(scale) =>
                                updateChartSettings({ scatter: { xScale: scale === 'log' ? 'logarithmic' : 'linear' } })
                            }
                        />
                    ),
                },
            xAxisBeginAtZero: showsAxes &&
                isScatterPlot && {
                    element: (
                        <BeginAtZeroOption
                            checked={chartSettings.scatter?.xStartAtZero ?? false}
                            onChange={(xStartAtZero) => updateChartSettings({ scatter: { xStartAtZero } })}
                        />
                    ),
                },
            xAxisDateFormat: showsAxes &&
                isDateXAxis && {
                    element: (
                        <ChartOptionTextInput
                            label="Date format"
                            info="For example, YYYY-MM-DD, MMM YYYY, or DD/MM/YYYY."
                            value={chartSettings.xAxisDateFormat}
                            placeholder="Automatic"
                            onChange={(xAxisDateFormat) => updateChartSettings({ xAxisDateFormat })}
                            data-attr="chart-date-format"
                        />
                    ),
                },
            xAxisTickRotation: showsSeriesOptions && {
                element: (
                    <ChartOptionSelect
                        label="Tick label rotation"
                        value={chartSettings.xAxisTickRotation ?? 'auto'}
                        options={TICK_ROTATION_OPTIONS}
                        onChange={(rotation) =>
                            updateChartSettings({ xAxisTickRotation: rotation === 'auto' ? undefined : rotation })
                        }
                    />
                ),
            },
            xAxisShowTicks: showsAxes && {
                element: (
                    <ChartOptionSwitch
                        label="Show tick labels"
                        checked={chartSettings.showXAxisTicks ?? true}
                        onChange={(showXAxisTicks) => updateChartSettings({ showXAxisTicks })}
                    />
                ),
            },
            // Quill's scatter draws both axis lines together, so a per-edge toggle can't be honored there.
            xAxisBorder: showsAxes &&
                !isScatterPlot && {
                    element: (
                        <ChartOptionSwitch
                            label="Show border"
                            checked={chartSettings.showXAxisBorder ?? true}
                            onChange={(showXAxisBorder) => updateChartSettings({ showXAxisBorder })}
                        />
                    ),
                },

            yAxisLabel: showsAxes && { element: leftYAxis.label },
            yAxisBeginAtZero: showsAxes && !isBoxPlot && { element: leftYAxis.beginAtZero },
            yAxisShowTicks: showsAxes && { element: leftYAxis.showTicks },
            yAxisGridLines: showsAxes && { element: leftYAxis.gridLines },
            yAxisBorder: showsAxes &&
                !isScatterPlot && {
                    element: (
                        <ChartOptionSwitch
                            label="Show border"
                            checked={chartSettings.showYAxisBorder ?? true}
                            onChange={(showYAxisBorder) => updateChartSettings({ showYAxisBorder })}
                        />
                    ),
                },
            yAxisScale: showsAxes && { element: leftYAxis.scale },

            rightYAxisLabel: showsRightYAxis && { element: rightYAxis.label },
            rightYAxisBeginAtZero: showsRightYAxis && { element: rightYAxis.beginAtZero },
            rightYAxisShowTicks: showsRightYAxis && { element: rightYAxis.showTicks },
            rightYAxisGridLines: showsRightYAxis && { element: rightYAxis.gridLines },
            rightYAxisScale: showsRightYAxis && { element: rightYAxis.scale },

            lineStyle: isLineChart && {
                element: (
                    <LineStyleOption
                        data-attr="data-visualization-line-style"
                        value={chartSettings.chartStyle?.curve ?? 'smooth'}
                        onChange={(curve) => updateChartSettings({ chartStyle: { curve } })}
                    />
                ),
            },
            trendLines: isScatterPlot && {
                element: (
                    <ChartOptionSwitch
                        label="Show line of best fit"
                        checked={chartSettings.scatter?.showBestFit ?? false}
                        onChange={(showBestFit) => updateChartSettings({ scatter: { showBestFit } })}
                    />
                ),
            },
        },
        {
            sections: {
                'x-axis': { title: categoryAxisName },
                'y-axis': { title: supportsRightYAxis ? `Left ${valueAxisName}` : valueAxisName },
                'right-y-axis': { title: `Right ${valueAxisName}` },
                annotations: { tooltip: null },
            },
        }
    )
}
