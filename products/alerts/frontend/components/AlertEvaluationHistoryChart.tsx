import { useMemo } from 'react'

import {
    ReferenceLines,
    ScatterChart,
    type ScatterPoint,
    type ScatterSeries,
    type ScatterTooltipContext,
    TooltipSurface,
    TooltipSwatch,
    useChartTheme,
} from '@posthog/quill-charts'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

const handleChartError = makeChartErrorHandler('alerts-evaluation-history-chart')

const ROLLING_WINDOW = 5

type PointClassification = 'historical' | 'currentOnly' | 'none'

interface HistoryPointMeta {
    label: string
    classification: PointClassification
}

// Semantic status colors, legible on light and dark chart surfaces: red = fired, orange = would
// fire now, indigo = normal.
const CLASSIFICATION_STYLE: Record<PointClassification, { color: string; shape: 'circle' | 'square' | 'triangle' }> = {
    none: { color: '#6366f1', shape: 'circle' },
    historical: { color: '#dc2626', shape: 'square' },
    currentOnly: { color: '#ea580c', shape: 'triangle' },
}

export interface AlertEvaluationHistoryPoint {
    label: string
    value: number
    firedAtTime?: boolean
    /**
     * Caller-computed classification against the CURRENT alert configuration.
     * `undefined`: the chart infers from `thresholds`. `null`: unclassifiable (e.g. the point
     * predates the current configuration revision), never flagged. `true`/`false`: explicit.
     */
    wouldFireUnderCurrentConfiguration?: boolean | null
}

export interface AlertEvaluationThreshold {
    direction: 'upper' | 'lower'
    value: number
    label: string
}

interface AlertEvaluationHistoryChartProps {
    points: AlertEvaluationHistoryPoint[]
    valueLabel: string
    thresholds: AlertEvaluationThreshold[]
    historyLimit: number
    evaluationsTotal?: number | null
    evaluationNoun?: string
    tableAvailable?: boolean
    classifyUnusualWithoutThresholds?: boolean
    formatValue?: (value: number) => string
}

function rollingMean(values: number[], window: number): number[] {
    const boundedWindow = Math.max(1, Math.min(window, values.length))
    const means: number[] = []
    for (let index = 0; index < values.length; index++) {
        const start = Math.max(0, index - boundedWindow + 1)
        const slice = values.slice(start, index + 1)
        means.push(slice.reduce((sum, value) => sum + value, 0) / slice.length)
    }
    return means
}

function detectSpikesAboveTrend(values: number[], trailingMean: number[]): boolean[] {
    if (values.length === 0) {
        return []
    }
    const minimum = Math.min(...values)
    const maximum = Math.max(...values)
    const range = maximum - minimum || Math.max(Math.abs(maximum), 1)
    const globalMean = values.reduce((sum, value) => sum + value, 0) / values.length
    const variance = values.reduce((sum, value) => sum + (value - globalMean) ** 2, 0) / values.length
    const standardDeviation = Math.sqrt(variance) || range * 0.05

    return values.map((value, index) => {
        const baseline = trailingMean[index] ?? value
        const margin = Math.max(0.12 * range, 0.85 * standardDeviation)
        return value > baseline + margin
    })
}

function matchesThreshold(value: number, thresholds: AlertEvaluationThreshold[]): boolean {
    return thresholds.some((threshold) => {
        if (threshold.direction === 'upper') {
            return value > threshold.value
        }
        return value < threshold.value
    })
}

function buildHistoryCaption(
    displayedCount: number,
    historyLimit: number,
    evaluationsTotal: number | null | undefined,
    evaluationNoun: string,
    tableAvailable: boolean
): string {
    const recentEvaluations = (count: number): string =>
        pluralize(count, `most recent ${evaluationNoun}`, `most recent ${evaluationNoun}s`)

    if (evaluationsTotal != null && evaluationsTotal > historyLimit) {
        const tableSuffix = tableAvailable ? ` Use the table for older ${evaluationNoun}s.` : ''
        return `Chart includes at most the ${recentEvaluations(historyLimit)}, from ${pluralize(
            evaluationsTotal,
            evaluationNoun
        )} total.${tableSuffix}`
    }
    if (displayedCount < historyLimit) {
        return `Chart includes the ${recentEvaluations(displayedCount)}.`
    }
    if (evaluationsTotal == null && displayedCount === historyLimit) {
        return `Chart includes at most the ${recentEvaluations(historyLimit)}.`
    }
    return `Chart includes the ${recentEvaluations(displayedCount)}.`
}

export function AlertEvaluationHistoryChart({
    points,
    valueLabel,
    thresholds,
    historyLimit,
    evaluationsTotal,
    evaluationNoun = 'check',
    tableAvailable = false,
    classifyUnusualWithoutThresholds = false,
    formatValue = humanFriendlyNumber,
}: AlertEvaluationHistoryChartProps): JSX.Element {
    const chartSeries = useMemo(
        () => ({
            values: points.map((point) => point.value),
            labels: points.map((point) => point.label),
        }),
        [points]
    )
    const { values, labels } = chartSeries
    const hasHistoricalFiringState = useMemo(() => points.some((point) => point.firedAtTime !== undefined), [points])

    const pointClassifications = useMemo((): PointClassification[] => {
        if (values.length === 0) {
            return []
        }
        if (hasHistoricalFiringState) {
            return points.map((point) => {
                if (point.firedAtTime) {
                    return 'historical'
                }
                if (point.wouldFireUnderCurrentConfiguration !== undefined) {
                    return point.wouldFireUnderCurrentConfiguration ? 'currentOnly' : 'none'
                }
                return matchesThreshold(point.value, thresholds) ? 'currentOnly' : 'none'
            })
        }
        if (thresholds.length > 0) {
            return values.map((value) => (matchesThreshold(value, thresholds) ? 'historical' : 'none'))
        }
        if (!classifyUnusualWithoutThresholds) {
            return values.map(() => 'none')
        }
        const window = Math.min(ROLLING_WINDOW, Math.max(2, Math.ceil(values.length / 4)))
        const trailingAverage = rollingMean(values, window)
        return detectSpikesAboveTrend(values, trailingAverage).map((flagged) => (flagged ? 'historical' : 'none'))
    }, [classifyUnusualWithoutThresholds, hasHistoricalFiringState, points, thresholds, values])

    const theme = useChartTheme()

    const scatterSeries = useMemo((): ScatterSeries<HistoryPointMeta>[] => {
        const byClass: Record<PointClassification, ScatterPoint<HistoryPointMeta>[]> = {
            none: [],
            historical: [],
            currentOnly: [],
        }
        points.forEach((point, index) => {
            const classification = pointClassifications[index] ?? 'none'
            byClass[classification].push({ x: index, y: point.value, meta: { label: point.label, classification } })
        })
        // Normal points first so flagged markers draw on top.
        return (['none', 'historical', 'currentOnly'] as const)
            .filter((classification) => byClass[classification].length > 0)
            .map((classification) => ({
                key: classification,
                label: classification,
                points: byClass[classification],
                shape: CLASSIFICATION_STYLE[classification].shape,
                color: CLASSIFICATION_STYLE[classification].color,
            }))
    }, [points, pointClassifications])

    const referenceLines = useMemo(
        () =>
            thresholds.map((threshold) => ({
                value: threshold.value,
                label: threshold.label,
                labelPosition: 'start' as const,
                variant: 'alert' as const,
            })),
        [thresholds]
    )

    const yDomain = useMemo((): readonly [number, number] | undefined => {
        if (thresholds.length === 0 || values.length === 0) {
            return undefined
        }
        const dataMin = Math.min(...values)
        const dataMax = Math.max(...values)
        const min = Math.min(dataMin, ...thresholds.map((threshold) => threshold.value))
        const max = Math.max(dataMax, ...thresholds.map((threshold) => threshold.value))
        if (min === dataMin && max === dataMax) {
            return undefined
        }
        const headroom = (max - min) * 0.05 || 1
        return [min < dataMin ? min - headroom : min, max > dataMax ? max + headroom : max]
    }, [thresholds, values])

    const renderTooltip = (ctx: ScatterTooltipContext<HistoryPointMeta>): JSX.Element => {
        const { point } = ctx
        const classification = point.meta?.classification ?? 'none'
        let suffix = ''
        if (classification === 'historical') {
            suffix = hasHistoricalFiringState
                ? ' (triggered the alert)'
                : thresholds.length > 0
                  ? ' (outside threshold)'
                  : ' (unusual compared to recent values)'
        } else if (classification === 'currentOnly') {
            suffix = ' (would trigger the alert now)'
        }
        return (
            <TooltipSurface>
                <div className="font-semibold">{point.meta?.label}</div>
                <div className="flex items-center gap-2">
                    <TooltipSwatch color={point.color} />
                    <span>
                        {valueLabel}: <strong className="tabular-nums">{formatValue(point.y)}</strong>
                        {suffix}
                    </span>
                </div>
            </TooltipSurface>
        )
    }

    const historicalCount = pointClassifications.filter((classification) => classification === 'historical').length
    const currentOnlyCount = pointClassifications.filter((classification) => classification === 'currentOnly').length
    const flaggedCount = historicalCount + currentOnlyCount
    const historyCaption = useMemo(
        () => buildHistoryCaption(points.length, historyLimit, evaluationsTotal, evaluationNoun, tableAvailable),
        [evaluationNoun, evaluationsTotal, historyLimit, points.length, tableAvailable]
    )

    let summary = 'Each hollow dot is one evaluation.'
    if (flaggedCount > 0) {
        const summaryParts: string[] = []
        if (historicalCount > 0) {
            if (hasHistoricalFiringState) {
                summaryParts.push(`${pluralize(historicalCount, evaluationNoun)} triggered the alert.`)
            } else if (thresholds.length > 0) {
                summaryParts.push(`${pluralize(historicalCount, evaluationNoun)} outside threshold.`)
            } else {
                summaryParts.push(`${pluralize(historicalCount, evaluationNoun)} flagged as unusual.`)
            }
        }
        if (currentOnlyCount > 0) {
            summaryParts.push(
                `${pluralize(currentOnlyCount, evaluationNoun)} would trigger the alert under the current thresholds.`
            )
        }
        summary = summaryParts.join(' ')
    } else if (hasHistoricalFiringState) {
        summary += ' Red squares mark evaluations that triggered the alert at the time they ran.'
    } else if (thresholds.length > 0) {
        summary += ' Red squares mark evaluations outside the configured threshold.'
    } else if (classifyUnusualWithoutThresholds) {
        summary += ' Red squares mark values flagged as unusual compared to recent values.'
    }
    if (thresholds.length > 0) {
        summary += ' Dashed lines are the configured alert thresholds.'
    }

    return (
        <div className="space-y-2">
            <p className="text-muted text-xs mb-0">{historyCaption}</p>
            <div className="h-56 w-full min-h-56 flex flex-col">
                <ScatterChart<HistoryPointMeta>
                    series={scatterSeries}
                    theme={theme}
                    config={{
                        xAxis: {
                            domain: [-0.5, Math.max(points.length - 0.5, 0.5)],
                            tickFormatter: (value) => labels[Math.round(value)] ?? '',
                        },
                        yAxis: { domain: yDomain, tickFormatter: (value) => formatValue(value) },
                        showGrid: true,
                        tooltip: { enabled: true },
                    }}
                    tooltip={renderTooltip}
                    onError={handleChartError}
                >
                    <ReferenceLines lines={referenceLines} />
                </ScatterChart>
            </div>
            <p className="text-muted text-xs mb-0">{summary}</p>
            {hasHistoricalFiringState && currentOnlyCount > 0 ? (
                <p className="text-muted text-xs mb-0">
                    Red squares fired at the time they ran. Orange triangles would fire under the current thresholds.
                </p>
            ) : null}
        </div>
    )
}
