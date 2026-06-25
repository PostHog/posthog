import React, { useMemo } from 'react'

import { ChartLegend } from '../../components/Legend/ChartLegend'
import { useChartLegend } from '../../components/Legend/useChartLegend'
import type {
    ChartLegendConfig,
    ChartTheme,
    DateRangeZoomData,
    LineChartConfig,
    PointClickData,
    Series,
    TooltipConfig,
    TooltipContext,
    YAxis,
} from '../../core/types'
import { ReferenceLines } from '../../overlays/ReferenceLine'
import { ValueLabels } from '../../overlays/ValueLabels'
import { buildGoalLineReferenceLines, goalLineValueDomain, type GoalLineConfig } from '../../utils/goal-lines'
import {
    buildYAxes,
    normalizeYAxisList,
    primaryYAxisConfig,
    useXTickFormatter,
    useYTickFormatter,
    type XAxisConfig,
    type YAxisConfig,
} from '../../utils/use-axis-formatters'
import { LineChart } from '../LineChart/LineChart'
import {
    resolveValueLabelsConfig,
    useSeriesWithValueLabelAllowlist,
    type ValueLabelsConfig,
} from '../utils/use-value-labels'
import {
    useDerivedSeries,
    type ConfidenceIntervalConfig,
    type MovingAverageConfig,
    type TrendLineConfig,
} from './utils/use-derived-series'

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
        tooltip: tooltipConfig,
        legend,
    } = config ?? {}
    const axisList = useMemo(() => normalizeYAxisList(yAxis), [yAxis])
    // Scalar y-config describes the primary (left) axis — drives single-axis rendering, the default
    // value-label formatter, and the left gutter when a right-axis series is present.
    const primaryYAxis = useMemo<YAxisConfig | undefined>(() => primaryYAxisConfig(axisList), [axisList])
    // Per-axis configs only when the caller passed an array — a single object keeps the existing
    // single-axis path untouched (no `yAxes` on the LineChart config).
    const yAxes = useMemo<YAxis[] | undefined>(
        () => (Array.isArray(yAxis) ? buildYAxes(axisList) : undefined),
        [yAxis, axisList]
    )

    const xTickFormatter = useXTickFormatter(xAxis, labels)
    const yTickFormatter = useYTickFormatter(primaryYAxis)

    // Toggling works off the raw series so the legend lists the user's series (not derived trend
    // lines / CI bands); hidden ones flow through the derived pipeline already excluded.
    const { visibleSeries, legendProps } = useChartLegend(series, theme, legend)

    const valueLabelsConfig = resolveValueLabelsConfig(valueLabels)
    const seriesAfterValueLabels = useSeriesWithValueLabelAllowlist(visibleSeries, valueLabelsConfig?.seriesKeys)

    const finalSeries = useDerivedSeries(seriesAfterValueLabels, {
        confidenceIntervals,
        movingAverage,
        trendLines,
        comparisonOf,
    })

    const valueLabelFormatter = valueLabelsConfig ? (valueLabelsConfig.formatter ?? yTickFormatter) : undefined

    const referenceLines = useMemo(() => buildGoalLineReferenceLines(goalLines, finalSeries), [goalLines, finalSeries])

    // Extend the value axis to cover goal lines that sit outside the data range, so a goal line
    // off the data's natural scale still renders inside the plot. Memoized so the `{ include }`
    // object stays referentially stable and doesn't re-trigger scale recomputation each render.
    const valueDomain = useMemo(() => goalLineValueDomain(referenceLines), [referenceLines])

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
