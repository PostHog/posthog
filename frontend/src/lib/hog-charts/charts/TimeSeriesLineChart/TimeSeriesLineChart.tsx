import React, { useMemo } from 'react'

import type { ChartTheme, LineChartConfig, PointClickData, Series, TooltipContext } from '../../core/types'
import { ReferenceLines } from '../../overlays/ReferenceLine'
import { ValueLabels } from '../../overlays/ValueLabels'
import { LineChart } from '../LineChart'
import {
    applyComparisonDimming,
    buildConfidenceIntervalSeries,
    buildMovingAverageSeries,
    buildTrendLineSeries,
} from './utils/derived-series'
import { buildGoalLineReferenceLines, type GoalLineConfig } from './utils/goal-lines'
import { applyInProgressToSeries, type InProgressConfig } from './utils/in-progress'
import { useXTickFormatter, useYTickFormatter, type XAxisConfig, type YAxisConfig } from './utils/use-axis-formatters'

export interface ValueLabelsConfig {
    seriesKeys?: string[]
    formatter?: (value: number) => string
}

export interface ConfidenceIntervalConfig {
    seriesKey: string
    lower: number[]
    upper: number[]
}

export interface MovingAverageConfig {
    seriesKey: string
    window: number
    label?: string
}

export interface TrendLineConfig {
    seriesKey: string
    kind: 'linear' | 'exponential'
    label?: string
}

export interface TimeSeriesLineChartConfig {
    xAxis?: XAxisConfig
    yAxis?: YAxisConfig
    inProgress?: InProgressConfig
    valueLabels?: boolean | ValueLabelsConfig
    goalLines?: GoalLineConfig[]
    confidenceIntervals?: ConfidenceIntervalConfig[]
    movingAverage?: MovingAverageConfig[]
    trendLines?: TrendLineConfig[]
    /** Map of comparison series key → its primary series key. Comparison series render
     *  at reduced opacity so they read as subordinate to their primary. */
    comparisonOf?: Record<string, string>
}

export interface TimeSeriesLineChartProps<Meta = unknown> {
    series: Series<Meta>[]
    labels: string[]
    theme: ChartTheme
    config?: TimeSeriesLineChartConfig
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    dataAttr?: string
    className?: string
    children?: React.ReactNode
}

function resolveValueLabelsConfig(valueLabels: TimeSeriesLineChartConfig['valueLabels']): ValueLabelsConfig | null {
    if (valueLabels === undefined || valueLabels === false) {
        return null
    }
    if (valueLabels === true) {
        return {}
    }
    return valueLabels
}

// JSON-stable signatures so inline config objects don't re-trigger derived-series
// recomputation on every render. Each config block is small (a handful of numbers
// plus a key) so JSON.stringify is cheap relative to the work it gates.
function stableKey(value: unknown): string | undefined {
    return value === undefined ? undefined : JSON.stringify(value)
}

export function TimeSeriesLineChart<Meta = unknown>({
    series,
    labels,
    theme,
    config,
    tooltip,
    onPointClick,
    dataAttr,
    className,
    children,
}: TimeSeriesLineChartProps<Meta>): React.ReactElement {
    const {
        xAxis,
        yAxis,
        inProgress,
        valueLabels,
        goalLines,
        confidenceIntervals,
        movingAverage,
        trendLines,
        comparisonOf,
    } = config ?? {}
    const xTickFormatter = useXTickFormatter(xAxis, labels)
    const yTickFormatter = useYTickFormatter(yAxis)

    const valueLabelsConfig = resolveValueLabelsConfig(valueLabels)

    const seriesWithInProgress = useMemo(
        () => applyInProgressToSeries(series, inProgress),
        [series, inProgress?.fromIndex]
    )

    // Stable primitive key so callers can pass `valueLabels: { seriesKeys: ['a'] }` inline
    // without re-running the transform on every render.
    const seriesKeysSignature = valueLabelsConfig?.seriesKeys?.join(' ')
    const seriesAfterValueLabels = useMemo(() => {
        const seriesKeys = valueLabelsConfig?.seriesKeys
        if (!seriesKeys) {
            return seriesWithInProgress
        }
        const allowed = new Set(seriesKeys)
        return seriesWithInProgress.map((s) =>
            allowed.has(s.key) ? s : { ...s, visibility: { ...s.visibility, fromValueLabels: true } }
        )
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [seriesWithInProgress, seriesKeysSignature])

    // Paint order = array order in LineChart.drawStatic. CI bands need to render behind
    // the main lines, MA / trend lines on top.
    const ciSignature = stableKey(confidenceIntervals)
    const ciSeries = useMemo(() => {
        if (!confidenceIntervals?.length) {
            return [] as Series<Meta>[]
        }
        const sourceByKey = new Map(seriesAfterValueLabels.map((s) => [s.key, s]))
        const out: Series<Meta>[] = []
        for (const ci of confidenceIntervals) {
            const source = sourceByKey.get(ci.seriesKey)
            if (!source) {
                continue
            }
            out.push(
                buildConfidenceIntervalSeries<Meta>({
                    seriesKey: source.key,
                    label: source.label,
                    baseColor: source.color,
                    lower: ci.lower,
                    upper: ci.upper,
                    yAxisId: source.yAxisId,
                    meta: source.meta,
                    excluded: source.visibility?.excluded,
                })
            )
        }
        return out
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [seriesAfterValueLabels, ciSignature])

    const maSignature = stableKey(movingAverage)
    const maSeries = useMemo(() => {
        if (!movingAverage?.length) {
            return [] as Series<Meta>[]
        }
        const sourceByKey = new Map(seriesAfterValueLabels.map((s) => [s.key, s]))
        const out: Series<Meta>[] = []
        for (const ma of movingAverage) {
            const source = sourceByKey.get(ma.seriesKey)
            if (!source) {
                continue
            }
            out.push(buildMovingAverageSeries<Meta>({ sourceSeries: source, window: ma.window, label: ma.label }))
        }
        return out
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [seriesAfterValueLabels, maSignature])

    const trendLinesSignature = stableKey(trendLines)
    const trendLineSeries = useMemo(() => {
        if (!trendLines?.length) {
            return [] as Series<Meta>[]
        }
        const sourceByKey = new Map(seriesAfterValueLabels.map((s) => [s.key, s]))
        const out: Series<Meta>[] = []
        for (const tl of trendLines) {
            const source = sourceByKey.get(tl.seriesKey)
            if (!source) {
                continue
            }
            out.push(buildTrendLineSeries<Meta>({ sourceSeries: source, kind: tl.kind, label: tl.label }))
        }
        return out
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [seriesAfterValueLabels, trendLinesSignature])

    const comparisonSignature = stableKey(comparisonOf)
    const finalSeries = useMemo(() => {
        const merged = [...ciSeries, ...seriesAfterValueLabels, ...maSeries, ...trendLineSeries]
        return applyComparisonDimming(merged, comparisonOf)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [ciSeries, seriesAfterValueLabels, maSeries, trendLineSeries, comparisonSignature])

    const valueLabelFormatter = valueLabelsConfig ? (valueLabelsConfig.formatter ?? yTickFormatter) : undefined

    const referenceLines = useMemo(() => buildGoalLineReferenceLines(goalLines, finalSeries), [goalLines, finalSeries])

    const lineChartConfig: LineChartConfig = {
        yScaleType: yAxis?.scale,
        xTickFormatter,
        yTickFormatter,
        hideXAxis: xAxis?.hide,
        hideYAxis: yAxis?.hide,
        showGrid: yAxis?.showGrid,
    }

    return (
        <LineChart
            series={finalSeries}
            labels={labels}
            config={lineChartConfig}
            theme={theme}
            tooltip={tooltip}
            onPointClick={onPointClick}
            className={className}
            dataAttr={dataAttr}
        >
            {referenceLines.length > 0 && <ReferenceLines lines={referenceLines} />}
            {valueLabelsConfig && <ValueLabels valueFormatter={valueLabelFormatter} />}
            {children}
        </LineChart>
    )
}
