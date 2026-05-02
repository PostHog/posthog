import annotationPlugin from 'chartjs-plugin-annotation'
import { useMemo } from 'react'

import { Chart } from 'lib/Chart'
import { useChart } from 'lib/hooks/useChart'
import { humanFriendlyNumber, pluralize } from 'lib/utils'

import { InsightThresholdType } from '~/queries/schema/schema-general'

import type { AlertHistoryChartPoint } from '../alertLogic'
import type { AlertType } from '../types'

export type { AlertHistoryChartPoint }

Chart.register(annotationPlugin)

const ROLLING_WINDOW = 5

type ThresholdLineMode = 'value' | 'anomaly_probability'

interface ChartThresholdContext {
    lower: number | null
    upper: number | null
    boundType: 'absolute' | 'percentage'
    lineMode: ThresholdLineMode
}

function getChartThresholdContext(alert: AlertType, chartPlotsAnomalyScore: boolean): ChartThresholdContext | null {
    const dc = alert.detector_config
    if (dc && typeof dc === 'object' && 'type' in dc) {
        if (dc.type === 'ensemble') {
            return null
        }
        if (dc.type === 'threshold') {
            const upper = 'upper_bound' in dc && typeof dc.upper_bound === 'number' ? dc.upper_bound : null
            const lower = 'lower_bound' in dc && typeof dc.lower_bound === 'number' ? dc.lower_bound : null
            if (upper == null && lower == null) {
                return null
            }
            return {
                lower,
                upper,
                boundType: 'absolute',
                lineMode: 'value',
            }
        }
        if (
            chartPlotsAnomalyScore &&
            'threshold' in dc &&
            typeof dc.threshold === 'number' &&
            !Number.isNaN(dc.threshold)
        ) {
            return {
                lower: null,
                upper: dc.threshold,
                boundType: 'absolute',
                lineMode: 'anomaly_probability',
            }
        }
        return null
    }

    const cfg = alert.threshold?.configuration
    const lower = cfg?.bounds?.lower ?? null
    const upper = cfg?.bounds?.upper ?? null
    if (lower == null && upper == null) {
        return null
    }
    return {
        lower,
        upper,
        boundType: cfg?.type === InsightThresholdType.PERCENTAGE ? 'percentage' : 'absolute',
        lineMode: 'value',
    }
}

function formatThresholdLabel(value: number, ctx: ChartThresholdContext): string {
    if (ctx.lineMode === 'anomaly_probability') {
        return `${Math.round(value * 100)}% prob.`
    }
    if (ctx.boundType === 'percentage') {
        return `${humanFriendlyNumber(value * 100)}% Δ`
    }
    return humanFriendlyNumber(value)
}

function rollingMean(values: number[], window: number): number[] {
    const w = Math.max(1, Math.min(window, values.length))
    const out: number[] = []
    for (let i = 0; i < values.length; i++) {
        const start = Math.max(0, i - w + 1)
        const slice = values.slice(start, i + 1)
        out.push(slice.reduce((a, b) => a + b, 0) / slice.length)
    }
    return out
}

/** Upward deviation from trailing mean — good enough to eyeball spikes in alert history. */
function detectSpikesAboveTrend(values: number[], trailingMean: number[]): boolean[] {
    if (values.length === 0) {
        return []
    }
    const minV = Math.min(...values)
    const maxV = Math.max(...values)
    const range = maxV - minV || Math.max(Math.abs(maxV), 1)
    const globalMean = values.reduce((a, b) => a + b, 0) / values.length
    const variance = values.reduce((s, v) => s + (v - globalMean) ** 2, 0) / values.length
    const std = Math.sqrt(variance) || range * 0.05

    return values.map((v, i) => {
        const baseline = trailingMean[i] ?? v
        const margin = Math.max(0.12 * range, 0.85 * std)
        return v > baseline + margin
    })
}

export function AlertHistoryChart({
    points,
    valueLabel,
    alert,
    chartPlotsAnomalyScore,
    historyLimit,
    checksTotal,
}: {
    points: AlertHistoryChartPoint[]
    valueLabel: string
    alert: AlertType
    chartPlotsAnomalyScore: boolean
    /** Max number of newest checks loaded for this chart (matches API `checks_limit`). */
    historyLimit: number
    /** Total checks for this alert when known (retrieve only); used to explain truncation. */
    checksTotal?: number | null
}): JSX.Element {
    const chartSeriesComputeds = useMemo(() => {
        const values = points.map((p) => p.value)
        const labels = points.map((p) => p.label)
        return { values, labels }
    }, [points])

    const { values, labels } = chartSeriesComputeds

    const thresholdCtx = useMemo(
        () => getChartThresholdContext(alert, chartPlotsAnomalyScore),
        [alert, chartPlotsAnomalyScore]
    )

    const hasHistoricalFiringState = useMemo(() => points.some((p) => p.firedAtTime !== undefined), [points])

    /**
     * Per-point visual state:
     *   'historical' — check actually fired at the time it ran (recorded on AlertCheck.state)
     *   'currentOnly' — didn't fire then, but would fire under the *current* thresholds (threshold tightened since)
     *   'none' — didn't fire then, wouldn't fire now
     *
     * When no historical state is present (e.g. Storybook fixtures), falls back to treating the current-threshold
     * / spike-heuristic match as 'historical' — preserves the pre-existing single-color behaviour for those cases.
     */
    const pointClass = useMemo((): ('historical' | 'currentOnly' | 'none')[] => {
        if (values.length === 0) {
            return []
        }
        const upper = thresholdCtx?.upper ?? null
        const lower = thresholdCtx?.lower ?? null
        const currentRuleFlag = (v: number): boolean => {
            if (upper != null && v > upper) {
                return true
            }
            if (lower != null && v < lower) {
                return true
            }
            return false
        }
        const canReapplyCurrentRule = upper != null || lower != null

        if (hasHistoricalFiringState) {
            return points.map((p, i) => {
                if (p.firedAtTime) {
                    return 'historical'
                }
                if (canReapplyCurrentRule && currentRuleFlag(values[i])) {
                    return 'currentOnly'
                }
                return 'none'
            })
        }
        if (canReapplyCurrentRule) {
            return values.map((v) => (currentRuleFlag(v) ? 'historical' : 'none'))
        }
        const window = Math.min(ROLLING_WINDOW, Math.max(2, Math.ceil(values.length / 4)))
        const trailingAvg = rollingMean(values, window)
        const spikeFlags = detectSpikesAboveTrend(values, trailingAvg)
        return spikeFlags.map((flag) => (flag ? 'historical' : 'none'))
    }, [values, points, thresholdCtx, hasHistoricalFiringState])

    const thresholdAnnotations = useMemo(() => {
        if (!thresholdCtx) {
            return undefined
        }
        const annotations: Record<string, Record<string, unknown>> = {}
        if (thresholdCtx.upper != null) {
            annotations.upperThreshold = {
                type: 'line',
                yMin: thresholdCtx.upper,
                yMax: thresholdCtx.upper,
                borderColor: 'rgba(220, 38, 38, 0.72)',
                borderWidth: 1.5,
                borderDash: [5, 4],
                label: {
                    display: true,
                    content: `Upper (${formatThresholdLabel(thresholdCtx.upper, thresholdCtx)})`,
                    position: 'start',
                    font: { size: 9 },
                    color: 'rgba(220, 38, 38, 0.95)',
                    backgroundColor: 'transparent',
                },
            }
        }
        if (thresholdCtx.lower != null) {
            annotations.lowerThreshold = {
                type: 'line',
                yMin: thresholdCtx.lower,
                yMax: thresholdCtx.lower,
                borderColor: 'rgba(234, 88, 12, 0.75)',
                borderWidth: 1.5,
                borderDash: [5, 4],
                label: {
                    display: true,
                    content: `Lower (${formatThresholdLabel(thresholdCtx.lower, thresholdCtx)})`,
                    position: 'start',
                    font: { size: 9 },
                    color: 'rgba(234, 88, 12, 0.95)',
                    backgroundColor: 'transparent',
                },
            }
        }
        return Object.keys(annotations).length > 0 ? annotations : undefined
    }, [thresholdCtx])

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
                        pointRadius: (ctx) => (pointClass[ctx.dataIndex] === 'none' ? 4 : 4.5),
                        pointHoverRadius: (ctx) => (pointClass[ctx.dataIndex] === 'none' ? 5 : 5.5),
                        // Shape encodes category so it's legible without relying on red/orange alone:
                        //   historical -> square, currentOnly -> triangle, none -> circle.
                        pointStyle: (ctx) => {
                            const cls = pointClass[ctx.dataIndex]
                            if (cls === 'historical') {
                                return 'rect'
                            }
                            if (cls === 'currentOnly') {
                                return 'triangle'
                            }
                            return 'circle'
                        },
                        pointBackgroundColor: (ctx) => {
                            const cls = pointClass[ctx.dataIndex]
                            if (cls === 'historical') {
                                return 'rgba(220, 38, 38, 0.92)'
                            }
                            if (cls === 'currentOnly') {
                                return 'rgba(234, 88, 12, 0.85)'
                            }
                            return 'transparent'
                        },
                        pointBorderColor: (ctx) => {
                            const cls = pointClass[ctx.dataIndex]
                            if (cls === 'historical') {
                                return 'rgba(127, 29, 29, 1)'
                            }
                            if (cls === 'currentOnly') {
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
                    legend: {
                        display: false,
                    },
                    ...(thresholdAnnotations ? { annotation: { annotations: thresholdAnnotations } } : {}),
                    tooltip: {
                        enabled: true,
                        callbacks: {
                            title: (items) => (items[0] ? String(items[0].label) : ''),
                            label: (ctx) => {
                                const y = ctx.parsed.y
                                if (y == null || Number.isNaN(y)) {
                                    return ctx.dataset.label ?? ''
                                }
                                const formatted = humanFriendlyNumber(y)
                                const cls = pointClass[ctx.dataIndex]
                                let tag = ''
                                if (cls === 'historical') {
                                    tag = hasHistoricalFiringState
                                        ? ' (triggered the alert)'
                                        : thresholdCtx && (thresholdCtx.upper != null || thresholdCtx.lower != null)
                                          ? ' (outside threshold)'
                                          : ' (unusual compared to recent values)'
                                } else if (cls === 'currentOnly') {
                                    tag = ' (would trigger the alert now)'
                                }
                                return `${valueLabel}: ${formatted}${tag}`
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        display: true,
                        ticks: {
                            maxRotation: 45,
                            minRotation: 0,
                            autoSkip: true,
                            maxTicksLimit: 6,
                            font: { size: 9 },
                        },
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
        deps: [
            chartSeriesComputeds,
            valueLabel,
            thresholdAnnotations,
            pointClass,
            thresholdCtx,
            hasHistoricalFiringState,
        ],
    })

    const historicalCount = pointClass.filter((c) => c === 'historical').length
    const currentOnlyCount = pointClass.filter((c) => c === 'currentOnly').length
    const flaggedCount = historicalCount + currentOnlyCount

    const historyCaption = useMemo((): string => {
        const displayedCount = points.length
        const recentChecksPhrase = (n: number): string => pluralize(n, 'most recent check', 'most recent checks')
        if (checksTotal != null && checksTotal > historyLimit) {
            return `Chart includes at most the ${recentChecksPhrase(historyLimit)}, from ${pluralize(checksTotal, 'check')} total. Use the table for older checks.`
        }
        if (displayedCount < historyLimit) {
            return `Chart includes the ${recentChecksPhrase(displayedCount)}.`
        }
        if (checksTotal == null && displayedCount === historyLimit) {
            return `Chart includes at most the ${recentChecksPhrase(historyLimit)}.`
        }
        return `Chart includes the ${recentChecksPhrase(displayedCount)}.`
    }, [historyLimit, checksTotal, points.length])

    return (
        <div className="space-y-2">
            <p className="text-muted text-xs mb-0">{historyCaption}</p>
            <div className="h-56 w-full min-h-56">
                <canvas ref={canvasRef} />
            </div>
            {flaggedCount > 0 ? (
                <p className="text-muted text-xs mb-0">
                    {historicalCount > 0 ? (
                        hasHistoricalFiringState ? (
                            `${pluralize(historicalCount, 'check')} triggered the alert.`
                        ) : thresholdCtx?.lineMode === 'anomaly_probability' ? (
                            `${pluralize(historicalCount, 'check')} above the probability cutoff.`
                        ) : thresholdCtx && (thresholdCtx.upper != null || thresholdCtx.lower != null) ? (
                            `${pluralize(historicalCount, 'check')} outside threshold.`
                        ) : (
                            `${pluralize(historicalCount, 'check')} flagged as unusual compared to recent values.`
                        )
                    ) : (
                        <>No checks triggered the alert at the time.</>
                    )}
                    {currentOnlyCount > 0 ? (
                        <>
                            {' '}
                            {historicalCount > 0
                                ? `${pluralize(currentOnlyCount, 'other check')} would`
                                : `${pluralize(currentOnlyCount, 'check')} would`}{' '}
                            trigger the alert under the current thresholds.
                        </>
                    ) : null}
                </p>
            ) : (
                <p className="text-muted text-xs mb-0">
                    {hasHistoricalFiringState
                        ? 'Each hollow dot is one evaluation. When present, red squares mark checks that triggered the alert at the time they ran.'
                        : thresholdCtx?.lineMode === 'anomaly_probability'
                          ? 'Each hollow dot is one evaluation. When present, red squares mark checks that triggered the alert above the cutoff.'
                          : thresholdCtx && (thresholdCtx.upper != null || thresholdCtx.lower != null)
                            ? 'Each hollow dot is one evaluation. When present, red squares mark checks that triggered the alert.'
                            : 'Each hollow dot is one evaluation. When present, red squares mark values flagged as unusual compared to recent values.'}{' '}
                    {thresholdCtx
                        ? chartPlotsAnomalyScore
                            ? 'Dashed lines are your configured alert thresholds (or detector probability cutoff).'
                            : 'Dashed lines are your configured alert thresholds.'
                        : 'Threshold lines appear when this alert has explicit bounds or a detector probability threshold.'}
                </p>
            )}
            {hasHistoricalFiringState && thresholdCtx && currentOnlyCount > 0 ? (
                <p className="text-muted text-xs mb-0">
                    {historicalCount > 0 ? 'Red squares fired at the time they ran. ' : ''}
                    Orange triangles would fire under the current thresholds but didn't when they ran.
                </p>
            ) : null}
        </div>
    )
}
