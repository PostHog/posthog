import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonBadge, LemonButton } from '@posthog/lemon-ui'

import { AxisLabelOption } from 'lib/components/ChartOptions/AxisLabelOption'
import { AxisScaleOption } from 'lib/components/ChartOptions/AxisScaleOption'
import { BeginAtZeroOption } from 'lib/components/ChartOptions/BeginAtZeroOption'
import { ChartOptionGroup } from 'lib/components/ChartOptions/ChartOptionGroup'
import { ChartOptionSelect } from 'lib/components/ChartOptions/ChartOptionSelect'
import { ChartOptionSwitch } from 'lib/components/ChartOptions/ChartOptionSwitch'
import { ChartOptionTextInput } from 'lib/components/ChartOptions/ChartOptionTextInput'
import { ChartOptionToggleGroup } from 'lib/components/ChartOptions/ChartOptionToggleGroup'
import { ExcludeOutliersOption } from 'lib/components/ChartOptions/ExcludeOutliersOption'
import { LegendOption } from 'lib/components/ChartOptions/LegendOption'
import { LineStyleOption } from 'lib/components/ChartOptions/LineStyleOption'
import { MetricOptions } from 'lib/components/ChartOptions/MetricOptions'
import { PercentOfTotalOption } from 'lib/components/ChartOptions/PercentOfTotalOption'
import { PieTotalOption } from 'lib/components/ChartOptions/PieTotalOption'
import { ValuesOnSeriesOption } from 'lib/components/ChartOptions/ValuesOnSeriesOption'
import { GoalLinesList } from 'lib/components/GoalLinesList'
import { PART_OF_WHOLE_DISPLAY_TYPES, PIE_DISPLAY_TYPES } from 'lib/constants'

import { ChartDisplayType } from '~/types'

import { dataVisualizationLogic } from '../dataVisualizationLogic'
import { displayLogic } from '../displayLogic'
import { buildPieSlices, partOfWholeChartData, showsLegendByDefault, showsPieTotal } from './Charts/sqlPieGraphAdapter'
import { SQL_METRIC_SUMMARY_DEFAULT } from './Charts/useSqlMetricModel'
import { DisplayTabPanel, DisplayTabPanels } from './DisplayTabPanels'
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

export const DisplayTab = (): JSX.Element => {
    const { effectiveVisualizationType, xData, yData, dataVisualizationProps } = useValues(dataVisualizationLogic)
    const { seriesBreakdownData } = useValues(seriesBreakdownLogic({ key: dataVisualizationProps.key }))
    const { goalLines, chartSettings, query } = useValues(displayLogic)
    const { addGoalLine, updateGoalLine, removeGoalLine, updateChartSettings } = useActions(displayLogic)

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
    const isMetric = effectiveVisualizationType === ChartDisplayType.Metric
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

    const renderYAxisSettings = (name: 'leftYAxisSettings' | 'rightYAxisSettings'): JSX.Element => {
        const leftPlaceholder = isHorizontalBarChart
            ? 'X-axis label'
            : supportsRightYAxis
              ? 'Left Y-axis label'
              : 'Y-axis label'
        const labelPlaceholder = name === 'leftYAxisSettings' ? leftPlaceholder : 'Right Y-axis label'

        return (
            <>
                <AxisLabelOption
                    data-attr={`data-visualization-${name === 'leftYAxisSettings' ? 'left' : 'right'}-y-axis-label-input`}
                    value={chartSettings[name]?.label}
                    placeholder={labelPlaceholder}
                    onChange={(label) => updateChartSettings({ [name]: { label } })}
                />
                <AxisScaleOption
                    value={chartSettings[name]?.scale === 'logarithmic' ? 'log' : 'linear'}
                    onChange={(scale) =>
                        updateChartSettings({ [name]: { scale: scale === 'log' ? 'logarithmic' : 'linear' } })
                    }
                />
                <ChartOptionSwitch
                    label="Show tick labels"
                    checked={chartSettings[name]?.showTicks ?? true}
                    onChange={(showTicks) => updateChartSettings({ [name]: { showTicks } })}
                />
                {!isBoxPlot && (
                    <BeginAtZeroOption
                        checked={
                            chartSettings[name]?.startAtZero ??
                            (isScatterPlot ? false : (chartSettings.yAxisAtZero ?? true))
                        }
                        onChange={(startAtZero) => updateChartSettings({ [name]: { startAtZero } })}
                    />
                )}
                <ChartOptionSwitch
                    label="Show grid lines"
                    checked={chartSettings[name]?.showGridLines ?? true}
                    onChange={(showGridLines) => updateChartSettings({ [name]: { showGridLines } })}
                />
            </>
        )
    }

    if (isMetric) {
        return (
            <DisplayTabPanels
                defaultOpenKeys={['general']}
                panels={[
                    {
                        key: 'general',
                        header: 'General',
                        content: (
                            <MetricOptions
                                settings={chartSettings.metric ?? {}}
                                defaultSummary={SQL_METRIC_SUMMARY_DEFAULT}
                                onChange={(metric) => updateChartSettings({ metric })}
                                summaryDataAttr="data-visualization-metric-summary"
                            />
                        ),
                    },
                ]}
            />
        )
    }

    const generalOptions = (
        <>
            <LegendOption
                showLegend={showLegend}
                onShowLegendChange={(value) => updateChartSettings({ showLegend: value })}
                position={chartSettings.legendPosition ?? (isProportionBar ? 'bottom' : isPieChart ? 'right' : 'top')}
                onPositionChange={(legendPosition) => updateChartSettings({ legendPosition })}
            />
            {isBoxPlot && (
                <ExcludeOutliersOption
                    checked={chartSettings.boxPlot?.excludeOutliers !== false}
                    onChange={(excludeOutliers) => updateChartSettings({ boxPlot: { excludeOutliers } })}
                />
            )}
            {supportsAnnotations && (
                <ChartOptionSwitch
                    label="Show annotations"
                    data-attr="data-visualization-show-annotations"
                    disabledReason={
                        !isDateXAxis ? 'Annotations need a Date or DateTime column on the X-axis' : undefined
                    }
                    checked={isDateXAxis && (chartSettings.showAnnotations ?? false)}
                    onChange={(showAnnotations) => updateChartSettings({ showAnnotations })}
                />
            )}
            {isPartOfWholeChart ? (
                <>
                    {isPieChart && (
                        <>
                            <ChartOptionToggleGroup
                                label="Show on slices"
                                value={chartSettings.pie?.sliceContent ?? 'values'}
                                options={PIE_SLICE_CONTENT_OPTIONS}
                                onChange={(sliceContent) => updateChartSettings({ pie: { sliceContent } })}
                            />
                            <ChartOptionToggleGroup
                                label="Show values as"
                                value={chartSettings.pie?.valueDisplay ?? 'absolute'}
                                options={PIE_VALUE_DISPLAY_OPTIONS}
                                onChange={(valueDisplay) => updateChartSettings({ pie: { valueDisplay } })}
                            />
                        </>
                    )}
                    <PieTotalOption
                        isDonut={isDonutChart}
                        checked={showsPieTotal(chartSettings, isProportionBar)}
                        onChange={(showTotal) => updateChartSettings({ pie: { showTotal } })}
                    />
                </>
            ) : (
                <>
                    {isScatterPlot && (
                        <ChartOptionSwitch
                            label="Show line of best fit"
                            checked={chartSettings.scatter?.showBestFit ?? false}
                            onChange={(showBestFit) => updateChartSettings({ scatter: { showBestFit } })}
                        />
                    )}
                    {isStackedBarChart && (
                        <PercentOfTotalOption
                            checked={chartSettings.stackBars100 ?? false}
                            onChange={(stackBars100) => updateChartSettings({ stackBars100 })}
                        />
                    )}
                    {!isSingleAxisChart && (
                        <>
                            <ChartOptionSwitch
                                label="Show total row"
                                checked={chartSettings.showTotalRow ?? true}
                                onChange={(showTotalRow) => updateChartSettings({ showTotalRow })}
                            />
                            <ChartOptionSwitch
                                label="Show nulls as zero"
                                checked={chartSettings.showNullsAsZero ?? false}
                                onChange={(showNullsAsZero) => updateChartSettings({ showNullsAsZero })}
                            />
                            <ValuesOnSeriesOption
                                checked={chartSettings.showValuesOnSeries ?? false}
                                onChange={(showValuesOnSeries) => updateChartSettings({ showValuesOnSeries })}
                            />
                        </>
                    )}
                    {chartSettings.showValuesOnSeries && !isSingleAxisChart && (
                        <>
                            {!isLineChart && (
                                <ChartOptionSelect
                                    label="Value position"
                                    value={chartSettings.valueLabelPosition ?? 'end'}
                                    options={VALUE_POSITION_OPTIONS}
                                    onChange={(valueLabelPosition) => updateChartSettings({ valueLabelPosition })}
                                />
                            )}
                            <ChartOptionSwitch
                                label="Value background"
                                checked={chartSettings.valueLabelBackground ?? true}
                                onChange={(valueLabelBackground) => updateChartSettings({ valueLabelBackground })}
                            />
                            <ChartOptionSelect
                                label="Value font size"
                                value={chartSettings.valueLabelFontSize ?? 12}
                                options={FONT_SIZE_OPTIONS}
                                onChange={(valueLabelFontSize) => updateChartSettings({ valueLabelFontSize })}
                            />
                            <ChartOptionSelect
                                label="Value rotation"
                                value={chartSettings.valueLabelRotation ?? 0}
                                options={ROTATION_OPTIONS}
                                onChange={(valueLabelRotation) => updateChartSettings({ valueLabelRotation })}
                            />
                        </>
                    )}
                    {(isStackedBarChart ||
                        isHorizontalBarChart ||
                        effectiveVisualizationType === ChartDisplayType.ActionsBar) && (
                        <ChartOptionSelect
                            label="Bar spacing"
                            value={chartSettings.barGap ?? 0.2}
                            options={BAR_GAP_OPTIONS}
                            onChange={(barGap) => updateChartSettings({ barGap })}
                        />
                    )}
                </>
            )}
        </>
    )

    // The horizontal bar chart swaps its axes, so the category axis is the Y-axis there.
    const categoryAxisName = isHorizontalBarChart ? 'Y-axis' : 'X-axis'
    const valueAxisName = isHorizontalBarChart ? 'X-axis' : 'Y-axis'
    const axesOptions = (
        <>
            <ChartOptionGroup title={categoryAxisName}>
                <AxisLabelOption
                    data-attr="data-visualization-x-axis-label-input"
                    value={chartSettings.xAxisLabel}
                    placeholder={`${categoryAxisName} label`}
                    onChange={(xAxisLabel) => updateChartSettings({ xAxisLabel })}
                />
                {isScatterPlot && (
                    <>
                        <AxisScaleOption
                            value={chartSettings.scatter?.xScale === 'logarithmic' ? 'log' : 'linear'}
                            onChange={(scale) =>
                                updateChartSettings({
                                    scatter: { xScale: scale === 'log' ? 'logarithmic' : 'linear' },
                                })
                            }
                        />
                        <BeginAtZeroOption
                            checked={chartSettings.scatter?.xStartAtZero ?? false}
                            onChange={(xStartAtZero) => updateChartSettings({ scatter: { xStartAtZero } })}
                        />
                    </>
                )}
                {isDateXAxis && (
                    <ChartOptionTextInput
                        label="Date format"
                        info="For example, YYYY-MM-DD, MMM YYYY, or DD/MM/YYYY."
                        value={chartSettings.xAxisDateFormat}
                        placeholder="Automatic"
                        onChange={(xAxisDateFormat) => updateChartSettings({ xAxisDateFormat })}
                        data-attr="chart-date-format"
                    />
                )}
                {!isSingleAxisChart && (
                    <ChartOptionSelect
                        label="Tick label rotation"
                        value={chartSettings.xAxisTickRotation ?? 'auto'}
                        options={TICK_ROTATION_OPTIONS}
                        onChange={(rotation) =>
                            updateChartSettings({ xAxisTickRotation: rotation === 'auto' ? undefined : rotation })
                        }
                    />
                )}
                <ChartOptionSwitch
                    label="Show tick labels"
                    checked={chartSettings.showXAxisTicks ?? true}
                    onChange={(showXAxisTicks) => updateChartSettings({ showXAxisTicks })}
                />
                {/* Quill's scatter draws both axis lines together, so a per-edge toggle can't be honored there. */}
                {!isScatterPlot && (
                    <ChartOptionSwitch
                        label="Show border"
                        checked={chartSettings.showXAxisBorder ?? true}
                        onChange={(showXAxisBorder) => updateChartSettings({ showXAxisBorder })}
                    />
                )}
            </ChartOptionGroup>
            <ChartOptionGroup title={supportsRightYAxis ? `Left ${valueAxisName}` : valueAxisName}>
                {renderYAxisSettings('leftYAxisSettings')}
                {!isScatterPlot && (
                    <ChartOptionSwitch
                        label="Show border"
                        checked={chartSettings.showYAxisBorder ?? true}
                        onChange={(showYAxisBorder) => updateChartSettings({ showYAxisBorder })}
                    />
                )}
            </ChartOptionGroup>
            {supportsRightYAxis && (
                <ChartOptionGroup title={`Right ${valueAxisName}`}>
                    {renderYAxisSettings('rightYAxisSettings')}
                </ChartOptionGroup>
            )}
        </>
    )

    const isBIVisualization = query.kind === 'BIVisualizationNode'
    const goalLinesOptions = (
        <>
            <GoalLinesList
                allowCalculations={isBIVisualization}
                calculationDisabledReason={
                    isStackedBarChart && chartSettings.stackBars100
                        ? 'Calculated lines are hidden on 100% stacked charts. Use a constant or turn off percentage stacking.'
                        : undefined
                }
                goalLines={goalLines}
                removeGoalLine={removeGoalLine}
                updateGoalLine={updateGoalLine}
            />
            <LemonButton onClick={addGoalLine} icon={<IconPlusSmall />} fullWidth>
                {isBIVisualization ? 'Add reference line' : 'Add goal line'}
            </LemonButton>
            {isBIVisualization && (
                <p className="text-xs text-secondary mb-0">
                    Calculations use returned marks on the left axis after aggregation and table calculations. Per
                    series adds a line for each color group or measure. Result limits apply.
                    {isStackedBarChart && chartSettings.stackBars100 && (
                        <span> Calculated lines are hidden on 100% stacked charts.</span>
                    )}
                </p>
            )}
        </>
    )

    const panels: DisplayTabPanel[] = [{ key: 'general', header: 'General', content: generalOptions }]
    if (!isPartOfWholeChart) {
        panels.push({ key: 'axes', header: 'Axes', content: axesOptions })
    }
    if (isLineChart) {
        panels.push({
            key: 'lines',
            header: 'Lines',
            content: (
                <LineStyleOption
                    data-attr="data-visualization-line-style"
                    value={chartSettings.chartStyle?.curve ?? 'smooth'}
                    onChange={(curve) => updateChartSettings({ chartStyle: { curve } })}
                />
            ),
        })
    }
    if (!isPartOfWholeChart && !isSingleAxisChart) {
        panels.push({
            key: 'goals',
            header: (
                <div className="flex items-center gap-1 flex-1">
                    <span className="flex-1">{isBIVisualization ? 'Reference lines' : 'Goal lines'}</span>
                    {goalLines.length > 0 && <LemonBadge.Number status="muted" size="small" count={goalLines.length} />}
                </div>
            ),
            content: goalLinesOptions,
        })
    }

    return <DisplayTabPanels defaultOpenKeys={['general']} panels={panels} />
}
