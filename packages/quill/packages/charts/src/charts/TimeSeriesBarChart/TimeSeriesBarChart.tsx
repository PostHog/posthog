import React from 'react'

import { ChartLegend } from '../../components/Legend/ChartLegend'
import type {
    BarChartConfig,
    BarFillStyle,
    ChartLegendConfig,
    ChartTheme,
    PointClickData,
    Series,
    TooltipConfig,
    TooltipContext,
} from '../../core/types'
import { ChartLoadingOverlay } from '../../overlays/ChartLoadingOverlay'
import { ReferenceLines } from '../../overlays/ReferenceLine'
import { TrendLineOverlay } from '../../overlays/TrendLineOverlay'
import { ValueLabels } from '../../overlays/ValueLabels'
import type { GoalLineConfig } from '../../utils/goal-lines'
import type { XAxisConfig, YAxisConfig } from '../../utils/use-axis-formatters'
import { BarChart } from '../BarChart/BarChart'
import { useTrendLineSeries, type TrendLineConfig } from '../utils/use-derived-series'
import {
    FALLBACK_SKELETON_LABELS,
    HIDDEN_TICK_FORMATTER,
    SKELETON_MARGINS,
    useLoadingSeries,
    type ChartLoadingProps,
} from '../utils/use-loading-state'
import { useGoalLines, useTimeSeries } from '../utils/use-time-series'
import type { ValueLabelsConfig } from '../utils/use-value-labels'

// Literal class string so Tailwind v4's `dist/*.js` source scan sees the utilities.
const REFRESHING_CLASS = 'opacity-60 transition-opacity'

export interface TimeSeriesBarChartConfig {
    xAxis?: XAxisConfig
    /** Single object for a standard left axis; array for dual left+right axes (pass `id` and `position` on each). */
    yAxis?: YAxisConfig | YAxisConfig[]
    valueLabels?: boolean | ValueLabelsConfig
    goalLines?: GoalLineConfig[]
    /** Defaults to `stacked`. */
    barLayout?: BarChartConfig['barLayout']
    /** Defaults to `vertical`. */
    axisOrientation?: BarChartConfig['axisOrientation']
    /** Stacked bars only round the topmost segment. */
    barCornerRadius?: number
    /** Show a vertical crosshair line that follows the cursor. */
    showCrosshair?: boolean
    /** Draw L-shaped axis baselines without grid lines (ignored when `yAxis.showGrid` is true). */
    showAxisLines?: boolean
    /** Draw short tick marks next to each visible axis label. Pairs with `showAxisLines`. */
    showTickMarks?: boolean
    /** Tooltip behaviour (pinning, placement). Tooltip *content* is the `tooltip` render prop. */
    tooltip?: TooltipConfig
    /** Stacked layout only — stack negatives below the zero baseline (d3.stackOffsetDiverging). */
    divergingStack?: boolean
    /** Bar fill treatment — `flat` (default), `gradient`, or `gloss`. */
    fillStyle?: BarFillStyle
    /** Ease the hover highlight in over this many ms (`true` = default duration). Omit to snap. */
    animateHover?: boolean | number
    /** Built-in legend with click-to-toggle series visibility. Hidden by default. */
    legend?: ChartLegendConfig
    /** Linear or exponential trend line overlays — rendered as SVG lines on top of the bars. */
    trendLines?: TrendLineConfig[]
}

export interface TimeSeriesBarChartProps<Meta = unknown> extends ChartLoadingProps {
    series: Series<Meta>[]
    labels: string[]
    theme: ChartTheme
    config?: TimeSeriesBarChartConfig
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    dataAttr?: string
    className?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export function TimeSeriesBarChart<Meta = unknown>({
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
    loading = false,
    refreshing = false,
    loadingOverlay,
}: TimeSeriesBarChartProps<Meta>): React.ReactElement {
    const {
        xAxis,
        yAxis,
        valueLabels,
        goalLines,
        barLayout,
        axisOrientation,
        barCornerRadius,
        showCrosshair,
        showAxisLines,
        showTickMarks,
        tooltip: tooltipConfig,
        divergingStack,
        fillStyle,
        animateHover,
        legend,
        trendLines,
    } = config ?? {}
    const isRefreshing = !loading && refreshing
    const busy = loading || isRefreshing
    // Without a known x-domain the skeleton still needs band positions; the fake labels are hidden.
    const hasKnownLabels = labels.length > 0
    const effectiveLabels = loading && !hasKnownLabels ? FALLBACK_SKELETON_LABELS : labels
    const skeletonSeries = useLoadingSeries<Meta>('bar', effectiveLabels, theme, loading)
    const inputSeries = skeletonSeries ?? series

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
    } = useTimeSeries(inputSeries, effectiveLabels, theme, {
        xAxis,
        yAxis,
        valueLabels: loading ? undefined : valueLabels,
        legend: loading ? undefined : legend,
    })

    // `axisOrientation` flows through `barChartConfig` into chart context, so `ReferenceLine`
    // reads it automatically — no need to stamp each line here.
    const { referenceLines, valueDomain } = useGoalLines(loading ? undefined : goalLines, chartSeries)

    const trendSeries = useTrendLineSeries(visibleSeries, loading ? undefined : trendLines)

    const barChartConfig: BarChartConfig = {
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
        barLayout,
        axisOrientation,
        showCrosshair: busy ? false : showCrosshair,
        tooltip: busy ? { enabled: false } : tooltipConfig,
        animateHover,
        yAxes: loading ? undefined : yAxes,
        bars: {
            cornerRadius: barCornerRadius,
            divergingStack,
            valueDomain,
            fillStyle,
        },
    }

    return (
        <ChartLegend {...legendProps} legendDataAttr="hog-chart-timeseries-bar-legend">
            <BarChart
                series={chartSeries}
                labels={effectiveLabels}
                config={barChartConfig}
                theme={theme}
                tooltip={busy ? undefined : tooltip}
                onPointClick={busy ? undefined : onPointClick}
                className={[className, isRefreshing ? REFRESHING_CLASS : undefined].filter(Boolean).join(' ') || undefined}
                dataAttr={dataAttr}
                onError={onError}
            >
                {!loading && referenceLines.length > 0 && <ReferenceLines lines={referenceLines} />}
                {!loading && trendSeries.length > 0 && <TrendLineOverlay trendSeries={trendSeries} />}
                {!loading && valueLabelsConfig && <ValueLabels valueFormatter={valueLabelFormatter} />}
                {!loading && children}
                {busy && <ChartLoadingOverlay>{loadingOverlay}</ChartLoadingOverlay>}
            </BarChart>
        </ChartLegend>
    )
}
