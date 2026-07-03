import React from 'react'

import { ChartLegend } from '../../components/Legend/ChartLegend'
import type {
    ChartLegendConfig,
    ChartTheme,
    DateRangeZoomData,
    LineChartConfig,
    PointClickData,
    Series,
    TooltipConfig,
    TooltipContext,
} from '../../core/types'
import { ReferenceLines } from '../../overlays/ReferenceLine'
import { ValueLabels } from '../../overlays/ValueLabels'
import type { GoalLineConfig } from '../../utils/goal-lines'
import type { XAxisConfig, YAxisConfig } from '../../utils/use-axis-formatters'
import { LineChart } from '../LineChart/LineChart'
import {
    useDerivedSeries,
    type ConfidenceIntervalConfig,
    type MovingAverageConfig,
    type TrendLineConfig,
} from '../utils/use-derived-series'
import { useGoalLines, useTimeSeries } from '../utils/use-time-series'
import type { ValueLabelsConfig } from '../utils/use-value-labels'

export type { ConfidenceIntervalConfig, MovingAverageConfig, TrendLineConfig }

export interface TimeSeriesLineChartConfig {
    xAxis?: XAxisConfig
    /** Single object = one y-axis (today's behavior). Array = one entry per axis for dual y-axis
     *  charts: set `id` (matches `Series.yAxisId`; first entry defaults to `'left'`) and `position`
     *  (`'left'`/`'right'`; first entry defaults to `'left'`, the rest to `'right'`). A series renders
     *  against a secondary axis when its `yAxisId` matches an entry's `id`. */
    yAxis?: YAxisConfig | YAxisConfig[]
    valueLabels?: boolean | ValueLabelsConfig
    goalLines?: GoalLineConfig[]
    confidenceIntervals?: ConfidenceIntervalConfig[]
    movingAverage?: MovingAverageConfig[]
    trendLines?: TrendLineConfig[]
    /** Comparison series keys mapped to their primary. Comparison series render dimmed. */
    comparisonOf?: Record<string, string>
    /** Render area-fill series as a 100% stacked view; y-axis becomes 0–100%. */
    percentStackView?: boolean
    /** Show a vertical crosshair line that follows the cursor. */
    showCrosshair?: boolean
    /** Draw L-shaped axis baselines without grid lines (ignored when `yAxis.showGrid` is true). */
    showAxisLines?: boolean
    /** Draw short tick marks next to each visible axis label. Pairs with `showAxisLines`. */
    showTickMarks?: boolean
    /** Line interpolation: `linear` (default) or `monotone` (smooth curve through every point). */
    curve?: 'linear' | 'monotone'
    /** Tooltip behaviour (pinning, placement). Tooltip *content* is the `tooltip` render prop. */
    tooltip?: TooltipConfig
    /** Built-in legend with click-to-toggle series visibility. Hidden by default. */
    legend?: ChartLegendConfig
}

export interface TimeSeriesLineChartProps<Meta = unknown> {
    series: Series<Meta>[]
    labels: string[]
    theme: ChartTheme
    config?: TimeSeriesLineChartConfig
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    onDateRangeZoom?: (data: DateRangeZoomData) => void
    dataAttr?: string
    className?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export function TimeSeriesLineChart<Meta = unknown>({
    series,
    labels,
    theme,
    config,
    tooltip,
    onPointClick,
    onDateRangeZoom,
    dataAttr,
    className,
    children,
    onError,
}: TimeSeriesLineChartProps<Meta>): React.ReactElement {
    const {
        xAxis,
        yAxis,
        valueLabels,
        goalLines,
        confidenceIntervals,
        movingAverage,
        trendLines,
        comparisonOf,
        percentStackView,
        showCrosshair,
        showAxisLines,
        showTickMarks,
        curve,
        tooltip: tooltipConfig,
        legend,
    } = config ?? {}
    const {
        xTickFormatter,
        yTickFormatter,
        legendProps,
        chartSeries,
        valueLabelsConfig,
        valueLabelFormatter,
        primaryYAxis,
        yAxes,
    } = useTimeSeries(series, labels, theme, { xAxis, yAxis, valueLabels, legend })

    const finalSeries = useDerivedSeries(chartSeries, {
        confidenceIntervals,
        movingAverage,
        trendLines,
        comparisonOf,
    })

    // Goal lines scale against the drawn (post-derived) series, unlike bar/combo.
    const { referenceLines, valueDomain } = useGoalLines(goalLines, finalSeries)

    // `startAtZero === false` floats the primary axis to its data range; the default (undefined/true)
    // keeps the baseline clamped to 0. A log scale has no zero baseline to clamp, so it's a no-op there.
    const floatBaseline = primaryYAxis?.startAtZero === false && primaryYAxis?.scale !== 'log'

    const lineChartConfig: LineChartConfig = {
        yScaleType: primaryYAxis?.scale,
        xTickFormatter,
        yTickFormatter,
        hideXAxis: xAxis?.hide,
        hideYAxis: primaryYAxis?.hide,
        xAxisLabel: xAxis?.label,
        yAxisLabel: primaryYAxis?.label,
        showGrid: primaryYAxis?.showGrid,
        showAxisLines,
        showTickMarks,
        curve,
        percentStackView,
        showCrosshair,
        tooltip: tooltipConfig,
        valueDomain,
        floatBaseline,
        yAxes,
    }

    return (
        <ChartLegend {...legendProps} legendDataAttr="hog-chart-timeseries-line-legend">
            <LineChart
                series={finalSeries}
                labels={labels}
                config={lineChartConfig}
                theme={theme}
                tooltip={tooltip}
                onPointClick={onPointClick}
                onDateRangeZoom={onDateRangeZoom}
                className={className}
                dataAttr={dataAttr}
                onError={onError}
            >
                {referenceLines.length > 0 && <ReferenceLines lines={referenceLines} />}
                {valueLabelsConfig && <ValueLabels valueFormatter={valueLabelFormatter} />}
                {children}
            </LineChart>
        </ChartLegend>
    )
}
