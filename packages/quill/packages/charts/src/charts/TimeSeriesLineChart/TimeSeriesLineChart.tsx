import React, { useMemo } from 'react'

import { ChartLegend } from '../../components/Legend/ChartLegend'
import { useResolvedChartTheme } from '../../core/theme'
import type {
    AxisLinesConfig,
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
import { buildTimeTickLabels, inferTimeInterval } from '../../utils/dates'
import { parseDateInTimezone } from '../../utils/dayjs'
import { mergeValueDomains, type GoalLineConfig } from '../../utils/goal-lines'
import { useTimeSeriesTooltipConfig, type XAxisConfig, type YAxisConfig } from '../../utils/use-axis-formatters'
import { LineChart } from '../LineChart/LineChart'
import {
    useDerivedSeries,
    type ConfidenceIntervalConfig,
    type MovingAverageConfig,
    type TrendLineConfig,
} from '../utils/use-derived-series'
import { useGoalLines, useTimeSeries, useValueBounds } from '../utils/use-time-series'
import type { ValueLabelsConfig } from '../utils/use-value-labels'

export type { ConfidenceIntervalConfig, MovingAverageConfig, TrendLineConfig }

export interface TimeSeriesLineChartConfig {
    valueDomain?: LineChartConfig['valueDomain']
    /** Reserve space for custom overlays; unspecified sides keep their computed margins. */
    margins?: LineChartConfig['margins']
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
    /** Stack the series. Omit to stack only when two or more series set `fill`. See
     *  {@link LineChartConfig.stacked}. */
    stacked?: boolean
    /** Show a vertical crosshair line that follows the cursor. */
    showCrosshair?: boolean
    /** Join the shared crosshair of an enclosing `ChartHoverSync`. Defaults to true. */
    syncHover?: boolean
    /** Horizontal grid lines, aligned to the primary y-axis ticks. `showGrid` on the primary
     *  `yAxis` config, when set, wins. */
    showGrid?: boolean
    /** Draw L-shaped axis baselines without grid lines (ignored when `yAxis.showGrid` is true). */
    showAxisLines?: AxisLinesConfig
    /** Draw short tick marks next to each visible axis label. Pairs with `showAxisLines`. */
    showTickMarks?: boolean
    /** Line interpolation: `linear` (default) or `monotone` (smooth curve through every point). */
    curve?: 'linear' | 'monotone'
    /** `time` places each point at its time instead of evenly by index, so uneven spacing and gaps
     *  in time show. Labels parse in `xAxis.timezone` (UTC when unset), and the ticks fall on a
     *  regular grid at `xAxis.interval`, inferred from the labels when unset. Defaults to `index`. */
    xScale?: 'index' | 'time'
    /** Time scale only: the x-axis span as `[from, to]` epoch milliseconds, for example a dashboard
     *  time range wider than the data. Defaults to the first and last label. */
    xDomain?: readonly [number, number]
    /** Draw lines and areas across missing (non-finite) values instead of breaking them. With
     *  `xScale: 'time'`, a number bridges only gaps up to that many milliseconds and breaks the line
     *  across longer ones, even where no label falls. See {@link LineChartConfig.connectNulls}. */
    connectNulls?: boolean | number
    /** Tooltip behaviour (pinning, placement). Tooltip *content* is the `tooltip` render prop. */
    tooltip?: TooltipConfig
    /** Built-in legend with click-to-toggle series visibility. Hidden by default. */
    legend?: ChartLegendConfig
}

export interface TimeSeriesLineChartProps<Meta = unknown> {
    series: Series<Meta>[]
    /** One x value per data index, unique across the array (use ISO date strings, not formatted
     *  display labels). The x-scale keys positions off these strings, so a repeated value
     *  collapses onto the first occurrence's position and draws the series backwards. Display
     *  formatting belongs in `xAxis.timezone`/`interval` (auto tick formatter) or `tickFormatter`. */
    labels: string[]
    /** Defaults to the nearest `ChartThemeProvider`, then the quill CSS vars. */
    theme?: ChartTheme
    config?: TimeSeriesLineChartConfig
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    /** Right-click counterpart of `onPointClick`. See `ChartProps.onPointContextMenu`. */
    onPointContextMenu?: (data: PointClickData<Meta>) => void
    onDateRangeZoom?: (data: DateRangeZoomData) => void
    dataAttr?: string
    className?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export function TimeSeriesLineChart<Meta = unknown>({
    series,
    labels,
    theme: themeProp,
    config,
    tooltip,
    onPointClick,
    onPointContextMenu,
    onDateRangeZoom,
    dataAttr,
    className,
    children,
    onError,
}: TimeSeriesLineChartProps<Meta>): React.ReactElement {
    const theme = useResolvedChartTheme(themeProp)
    const {
        xAxis,
        yAxis,
        margins,
        valueLabels,
        goalLines,
        confidenceIntervals,
        movingAverage,
        trendLines,
        comparisonOf,
        percentStackView,
        stacked,
        showCrosshair,
        syncHover = true,
        showGrid,
        showAxisLines,
        showTickMarks,
        curve,
        xScale,
        xDomain,
        connectNulls,
        tooltip: tooltipConfig,
        legend,
    } = config ?? {}
    const time = useTimeScale(xScale === 'time', labels, xAxis, xDomain)
    const {
        xTickFormatter,
        yTickFormatter,
        legendProps,
        chartSeries,
        valueLabelsConfig,
        valueLabelFormatter,
        primaryYAxis,
        yAxes,
    } = useTimeSeries(series, labels, theme, {
        xAxis: time?.xAxis ?? xAxis,
        yAxis,
        valueLabels,
        legend,
        isPercent: !!percentStackView,
    })
    const timeSeriesTooltipConfig = useTimeSeriesTooltipConfig(tooltipConfig, xAxis, labels)

    const finalSeries = useDerivedSeries(chartSeries, {
        confidenceIntervals,
        movingAverage,
        trendLines,
        comparisonOf,
    })

    // Goal lines scale against the drawn (post-derived) series, unlike bar/combo.
    const { referenceLines, valueDomain: goalLineDomain } = useGoalLines(goalLines, finalSeries)
    const boundsDomain = useValueBounds(primaryYAxis)
    // A capped axis still has to stretch to reach an off-scale goal line.
    const valueDomain = useMemo(
        () => mergeValueDomains(config?.valueDomain, mergeValueDomains(goalLineDomain, boundsDomain)),
        [config?.valueDomain, goalLineDomain, boundsDomain]
    )

    // `startAtZero === false` floats the primary axis to its data range; the default (undefined/true)
    // keeps the baseline clamped to 0. A log scale has no zero baseline to clamp, so it's a no-op there.
    const floatBaseline = primaryYAxis?.startAtZero === false && primaryYAxis?.scale !== 'log'

    const lineChartConfig: LineChartConfig = {
        margins,
        yScaleType: primaryYAxis?.scale,
        xTickFormatter,
        xTickLabelRotation: xAxis?.tickLabelRotation,
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
        timeScale: time?.timeScale,
        xTickLabels: time?.xAxis.allDays,
        connectNulls,
        percentStackView,
        stacked,
        showCrosshair,
        syncHover,
        tooltip: timeSeriesTooltipConfig,
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
                onPointContextMenu={onPointContextMenu}
                onDateRangeZoom={onDateRangeZoom}
                className={className}
                dataAttr={dataAttr}
                onError={onError}
            >
                {referenceLines.length > 0 && <ReferenceLines lines={referenceLines} />}
                {valueLabelsConfig && (
                    <ValueLabels {...valueLabelsConfig} position="end" valueFormatter={valueLabelFormatter} />
                )}
                {children}
            </LineChart>
        </ChartLegend>
    )
}

/** For `xScale: 'time'`: a cached label parser and domain for `LineChart.timeScale`, plus the x-axis
 *  config with a regular tick grid across the domain as its labels. */
function useTimeScale(
    enabled: boolean,
    labels: string[],
    xAxis: XAxisConfig | undefined,
    xDomain: readonly [number, number] | undefined
): { timeScale: NonNullable<LineChartConfig['timeScale']>; xAxis: XAxisConfig & { allDays: string[] } } | null {
    const timezone = xAxis?.timezone ?? 'UTC'
    const parse = useMemo(() => {
        // Every series' points and every redraw parse the same labels, so parse each once. New labels
        // start a new cache, so a rolling window doesn't keep every label it has shown.
        const cache = new Map<string, number>()
        return (label: string): number => {
            let t = cache.get(label)
            if (t === undefined) {
                t = parseDateInTimezone(label, timezone).valueOf()
                cache.set(label, t)
            }
            return t
        }
    }, [timezone, labels])
    const [from, to] = xDomain ?? [parse(labels[0] ?? ''), parse(labels[labels.length - 1] ?? '')]
    const configInterval = xAxis?.interval
    const interval = useMemo(
        () => (enabled ? (configInterval ?? inferTimeInterval(labels, timezone) ?? 'day') : 'day'),
        [enabled, configInterval, labels, timezone]
    )
    const tickLabels = useMemo(
        () => (enabled ? buildTimeTickLabels(from, to, interval, timezone) : []),
        [enabled, from, to, interval, timezone]
    )
    return useMemo(
        () =>
            enabled
                ? {
                      timeScale: { parse, domain: [from, to] as const },
                      xAxis: { ...xAxis, timezone, interval, allDays: tickLabels },
                  }
                : null,
        [enabled, parse, from, to, xAxis, timezone, interval, tickLabels]
    )
}
