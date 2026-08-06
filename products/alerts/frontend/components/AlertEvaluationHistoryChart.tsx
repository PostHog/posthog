import annotationPlugin from 'chartjs-plugin-annotation'
import { useMemo } from 'react'

import { Chart } from 'lib/Chart'
import { useChart } from 'lib/hooks/useChart'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

Chart.register(annotationPlugin)

const ROLLING_WINDOW = 5

type PointClassification = 'historical' | 'currentOnly' | 'none'

export interface AlertEvaluationHistoryPoint {
    label: string
    value: number
    firedAtTime?: boolean
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

    const thresholdAnnotations = useMemo(() => {
        if (thresholds.length === 0) {
            return undefined
        }
        return Object.fromEntries(
            thresholds.map((threshold, index) => [
                `${threshold.direction}-${index}`,
                {
                    type: 'line' as const,
                    yMin: threshold.value,
                    yMax: threshold.value,
                    borderColor:
                        threshold.direction === 'upper' ? 'rgba(220, 38, 38, 0.72)' : 'rgba(234, 88, 12, 0.75)',
                    borderWidth: 1.5,
                    borderDash: [5, 4],
                    label: {
                        display: true,
                        content: threshold.label,
                        position: 'start' as const,
                        font: { size: 9 },
                        color: threshold.direction === 'upper' ? 'rgba(220, 38, 38, 0.95)' : 'rgba(234, 88, 12, 0.95)',
                        backgroundColor: 'transparent',
                    },
                },
            ])
        )
    }, [thresholds])

    const { canvasRef } = useChart({
        getConfig: () => ({
            type: 'line' as const,
            data: {
                labels,
                datasets: [
                    {
                        label: valueLabel,
                        data: values,
                        showLine: false,
                        borderWidth: 0,
                        backgroundColor: 'transparent',
                        fill: false,
                        pointRadius: (context) => (pointClassifications[context.dataIndex] === 'none' ? 4 : 4.5),
                        pointHoverRadius: (context) => (pointClassifications[context.dataIndex] === 'none' ? 5 : 5.5),
                        pointStyle: (context) => {
                            const classification = pointClassifications[context.dataIndex]
                            if (classification === 'historical') {
                                return 'rect'
                            }
                            if (classification === 'currentOnly') {
                                return 'triangle'
                            }
                            return 'circle'
                        },
                        pointBackgroundColor: (context) => {
                            const classification = pointClassifications[context.dataIndex]
                            if (classification === 'historical') {
                                return 'rgba(220, 38, 38, 0.92)'
                            }
                            if (classification === 'currentOnly') {
                                return 'rgba(234, 88, 12, 0.85)'
                            }
                            return 'transparent'
                        },
                        pointBorderColor: (context) => {
                            const classification = pointClassifications[context.dataIndex]
                            if (classification === 'historical') {
                                return 'rgba(127, 29, 29, 1)'
                            }
                            if (classification === 'currentOnly') {
                                return 'rgba(154, 52, 18, 1)'
                            }
                            return 'rgba(99, 102, 241, 0.95)'
                        },
                        pointBorderWidth: 1.75,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'nearest' as const, axis: 'x' as const, intersect: false },
                plugins: {
                    legend: { display: false },
                    ...(thresholdAnnotations ? { annotation: { annotations: thresholdAnnotations } } : {}),
                    tooltip: {
                        enabled: true,
                        callbacks: {
                            title: (items) => (items[0] ? String(items[0].label) : ''),
                            label: (context) => {
                                const value = context.parsed.y
                                if (value == null || Number.isNaN(value)) {
                                    return context.dataset.label ?? ''
                                }
                                const classification = pointClassifications[context.dataIndex]
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
                                return `${valueLabel}: ${humanFriendlyNumber(value)}${suffix}`
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        display: true,
                        ticks: { maxRotation: 45, minRotation: 0, autoSkip: true, maxTicksLimit: 6, font: { size: 9 } },
                        grid: { display: true, color: 'rgba(0,0,0,0.06)', drawTicks: false },
                    },
                    y: {
                        display: true,
                        position: 'left' as const,
                        ticks: {
                            maxTicksLimit: 5,
                            font: { size: 10 },
                            callback: (value: string | number) => humanFriendlyNumber(Number(value)),
                        },
                        grid: { color: 'rgba(0,0,0,0.06)' },
                    },
                },
            },
        }),
        deps: [chartSeries, valueLabel, thresholdAnnotations, pointClassifications, hasHistoricalFiringState],
    })

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
            <div className="h-56 w-full min-h-56">
                <canvas ref={canvasRef} />
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
