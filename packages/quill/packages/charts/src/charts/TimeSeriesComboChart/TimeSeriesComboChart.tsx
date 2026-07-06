import React from 'react'

import { ChartLegend } from '../../components/Legend/ChartLegend'
import type {
    AxisLinesConfig,
    ChartLegendConfig,
    ChartTheme,
    ComboChartConfig,
    PointClickData,
    SeriesType,
    Series,
    TooltipConfig,
    TooltipContext,
} from '../../core/types'
import { ReferenceLines } from '../../overlays/ReferenceLine'
import { TrendLineOverlay } from '../../overlays/TrendLineOverlay'
import { ValueLabels } from '../../overlays/ValueLabels'
import type { GoalLineConfig } from '../../utils/goal-lines'
import { useTimeSeriesTooltipConfig, type XAxisConfig, type YAxisConfig } from '../../utils/use-axis-formatters'
import { ComboChart } from '../ComboChart/ComboChart'
import { useTrendLineSeries, type TrendLineConfig } from '../utils/use-derived-series'
import { useGoalLines, useTimeSeries } from '../utils/use-time-series'
import type { ValueLabelsConfig } from '../utils/use-value-labels'

export interface TimeSeriesComboChartConfig {
    xAxis?: XAxisConfig
    /** Single object for a standard left axis; array for dual left+right axes. */
    yAxis?: YAxisConfig | YAxisConfig[]
    valueLabels?: boolean | ValueLabelsConfig
    goalLines?: GoalLineConfig[]
    /** Type used for series that don't set {@link Series.type}. Defaults to `'line'`. */
    defaultSeriesType?: SeriesType
    /** Layout applied to *bar* series only — lines and areas never stack or group. Defaults to
     *  `'stacked'`. */
    barLayout?: ComboChartConfig['barLayout']
    /** Stacked bars only round the topmost segment. */
    barCornerRadius?: number
    /** Show a vertical crosshair line that follows the cursor. */
    showCrosshair?: boolean
    /** Horizontal grid lines, aligned to the primary y-axis ticks. `showGrid` on the primary
     *  `yAxis` config, when set, wins. */
    showGrid?: boolean
    /** Draw L-shaped axis baselines without grid lines (ignored when `yAxis.showGrid` is true). */
    showAxisLines?: AxisLinesConfig
    /** Draw short tick marks next to each visible axis label. Pairs with `showAxisLines`. */
    showTickMarks?: boolean
    /** Line interpolation for line/area series: `linear` (default) or `monotone` (smooth curve). */
    curve?: 'linear' | 'monotone'
    /** Tooltip behaviour (pinning, placement). Tooltip *content* is the `tooltip` render prop. */
    tooltip?: TooltipConfig
    /** Built-in legend with click-to-toggle series visibility. Hidden by default. */
    legend?: ChartLegendConfig
    /** Trend line overlays rendered as SVG lines on top of the chart. */
    trendLines?: TrendLineConfig[]
}

export interface TimeSeriesComboChartProps<Meta = unknown> {
    series: Series<Meta>[]
    labels: string[]
    theme: ChartTheme
    config?: TimeSeriesComboChartConfig
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    dataAttr?: string
    className?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

/** Time-indexed {@link ComboChart}: mixed bar + line/area series on a timezone/interval-aware band
 *  x-axis, plus the time-series chrome `ComboChart` lacks — date x-axis, goal lines, a built-in
 *  legend, and value labels. Mirrors {@link TimeSeriesBarChart}/{@link TimeSeriesLineChart}. */
export function TimeSeriesComboChart<Meta = unknown>({
    series,
    labels,
    theme,
    config,
    tooltip,
    onPointClick,
    dataAttr,
    className,
    children,
    onError,
}: TimeSeriesComboChartProps<Meta>): React.ReactElement {
    const {
        xAxis,
        yAxis,
        valueLabels,
        goalLines,
        defaultSeriesType,
        barLayout,
        barCornerRadius,
        showCrosshair,
        showGrid,
        showAxisLines,
        showTickMarks,
        curve,
        tooltip: tooltipConfig,
        legend,
        trendLines,
    } = config ?? {}
    const {
        xTickFormatter,
        yTickFormatter,
        legendProps,
        visibleSeries,
        chartSeries,
        valueLabelsConfig,
        valueLabelFormatter,
        primaryYAxis,
        yAxes,
    } = useTimeSeries(series, labels, theme, { xAxis, yAxis, valueLabels, legend })
    const timeSeriesTooltipConfig = useTimeSeriesTooltipConfig(tooltipConfig, xAxis)

    const { referenceLines, valueDomain } = useGoalLines(goalLines, chartSeries)

    const trendSeries = useTrendLineSeries(visibleSeries, trendLines)

    const comboChartConfig: ComboChartConfig = {
        yScaleType: primaryYAxis?.scale,
        xTickFormatter,
        yTickFormatter,
        hideXAxis: xAxis?.hide,
        // Multi-axis: each axis hides its own gutter; collapse globally only when all are hidden.
        hideYAxis: yAxes ? yAxes.length > 0 && yAxes.every((a) => a.hide) : primaryYAxis?.hide,
        xAxisLabel: xAxis?.label,
        yAxisLabel: primaryYAxis?.label,
        showGrid: primaryYAxis?.showGrid ?? showGrid,
        showAxisLines,
        showTickMarks,
        curve,
        showCrosshair,
        defaultSeriesType,
        barLayout,
        barCornerRadius,
        tooltip: timeSeriesTooltipConfig,
        valueDomain,
        yAxes,
    }

    return (
        <ChartLegend {...legendProps} legendDataAttr="hog-chart-timeseries-combo-legend">
            <ComboChart
                series={chartSeries}
                labels={labels}
                config={comboChartConfig}
                theme={theme}
                tooltip={tooltip}
                onPointClick={onPointClick}
                className={className}
                dataAttr={dataAttr}
                onError={onError}
            >
                {referenceLines.length > 0 && <ReferenceLines lines={referenceLines} />}
                {trendSeries.length > 0 && <TrendLineOverlay trendSeries={trendSeries} />}
                {valueLabelsConfig && <ValueLabels valueFormatter={valueLabelFormatter} />}
                {children}
            </ComboChart>
        </ChartLegend>
    )
}
