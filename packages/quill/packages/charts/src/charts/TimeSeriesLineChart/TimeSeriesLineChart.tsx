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
import { ChartLoadingOverlay } from '../../overlays/ChartLoadingOverlay'
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
import {
    FALLBACK_SKELETON_LABELS,
    HIDDEN_TICK_FORMATTER,
    SKELETON_MARGINS,
    SKELETON_VALUE_DOMAIN,
    useLoadingSeries,
    type ChartLoadingProps,
} from '../utils/use-loading-state'
import { useGoalLines, useTimeSeries } from '../utils/use-time-series'
import type { ValueLabelsConfig } from '../utils/use-value-labels'

export type { ChartLoadingProps, ConfidenceIntervalConfig, MovingAverageConfig, TrendLineConfig }

// Literal class string so Tailwind v4's `dist/*.js` source scan sees the utilities.
const REFRESHING_CLASS = 'opacity-60 transition-opacity'

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

export interface TimeSeriesLineChartProps<Meta = unknown> extends ChartLoadingProps {
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
    loading = false,
    refreshing = false,
    loadingOverlay,
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
    const isRefreshing = !loading && refreshing
    const busy = loading || isRefreshing
    // Without a known x-domain the skeleton still needs band positions; the fake labels are hidden.
    const hasKnownLabels = labels.length > 0
    const effectiveLabels = loading && !hasKnownLabels ? FALLBACK_SKELETON_LABELS : labels
    const skeletonSeries = useLoadingSeries<Meta>('line', effectiveLabels, theme, loading)
    const inputSeries = skeletonSeries ?? series

    const {
        xTickFormatter,
        yTickFormatter,
        legendProps,
        chartSeries,
        valueLabelsConfig,
        valueLabelFormatter,
        primaryYAxis,
        yAxes,
    } = useTimeSeries(inputSeries, effectiveLabels, theme, {
        xAxis,
        yAxis,
        valueLabels: loading ? undefined : valueLabels,
        legend: loading ? undefined : legend,
    })

    const finalSeries = useDerivedSeries(
        chartSeries,
        loading
            ? {}
            : {
                  confidenceIntervals,
                  movingAverage,
                  trendLines,
                  comparisonOf,
              }
    )

    // Goal lines scale against the drawn (post-derived) series, unlike bar/combo.
    const { referenceLines, valueDomain } = useGoalLines(loading ? undefined : goalLines, finalSeries)

    // `startAtZero === false` floats the primary axis to its data range; the default (undefined/true)
    // keeps the baseline clamped to 0. A log scale has no zero baseline to clamp, so it's a no-op there.
    const floatBaseline = primaryYAxis?.startAtZero === false && primaryYAxis?.scale !== 'log'

    const lineChartConfig: LineChartConfig = {
        yScaleType: primaryYAxis?.scale,
        xTickFormatter,
        // Skeleton y values are fake — hide the tick text but keep a stable gutter via margins.
        yTickFormatter: loading ? HIDDEN_TICK_FORMATTER : yTickFormatter,
        margins: loading ? SKELETON_MARGINS : undefined,
        hideXAxis: xAxis?.hide || (loading && !hasKnownLabels),
        hideYAxis: primaryYAxis?.hide,
        xAxisLabel: xAxis?.label,
        yAxisLabel: primaryYAxis?.label,
        showGrid: primaryYAxis?.showGrid,
        showAxisLines,
        showTickMarks,
        curve,
        percentStackView: loading ? undefined : percentStackView,
        showCrosshair: busy ? false : showCrosshair,
        tooltip: busy ? { enabled: false } : tooltipConfig,
        // The drifting skeleton wave needs a pinned domain — data-derived scaling would pump.
        valueDomain: loading ? SKELETON_VALUE_DOMAIN : valueDomain,
        floatBaseline,
        yAxes: loading ? undefined : yAxes,
    }

    return (
        <ChartLegend {...legendProps} legendDataAttr="hog-chart-timeseries-line-legend">
            <LineChart
                series={finalSeries}
                labels={effectiveLabels}
                config={lineChartConfig}
                theme={theme}
                tooltip={busy ? undefined : tooltip}
                onPointClick={busy ? undefined : onPointClick}
                onDateRangeZoom={busy ? undefined : onDateRangeZoom}
                className={[className, isRefreshing ? REFRESHING_CLASS : undefined].filter(Boolean).join(' ') || undefined}
                dataAttr={dataAttr}
                onError={onError}
            >
                {!loading && referenceLines.length > 0 && <ReferenceLines lines={referenceLines} />}
                {!loading && valueLabelsConfig && <ValueLabels valueFormatter={valueLabelFormatter} />}
                {!loading && children}
                {busy && <ChartLoadingOverlay>{loadingOverlay}</ChartLoadingOverlay>}
            </LineChart>
        </ChartLegend>
    )
}
