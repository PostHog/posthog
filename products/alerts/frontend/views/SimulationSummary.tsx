import { useState } from 'react'

import {
    type AnomalyMarker,
    AnomalyPointsLayer,
    DEFAULT_Y_AXIS_ID,
    ReferenceLine,
    type Series,
    TimeSeriesLineChart,
    useChartTheme,
} from '@posthog/quill-charts'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { DetectorConfig } from '~/queries/schema/schema-general'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { AlertSimulationResult, BreakdownSimulationResult } from '../types'

const handleChartError = makeChartErrorHandler('alerts-simulation-chart')

interface SimSeriesMeta {
    isScore: boolean
}

/** Format a date string compactly: "Mar 16, 11:00" or "Mar 16" if midnight. */
function formatSimDate(dateStr: string): string {
    const d = new Date(dateStr)
    if (isNaN(d.getTime())) {
        return dateStr
    }
    const month = d.toLocaleString('en-US', { month: 'short' })
    const day = d.getDate()
    const hours = d.getHours()
    const mins = d.getMinutes()
    if (hours === 0 && mins === 0) {
        return `${month} ${day}`
    }
    return `${month} ${day}, ${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}`
}

/** Extract the sensitivity threshold from detector config (0-1 range). */
function getThreshold(config: DetectorConfig | null | undefined): number | null {
    if (!config) {
        return null
    }
    const c = config as Record<string, any>
    // ensemble doesn't have a single threshold
    if (c.type === 'ensemble' || c.type === 'threshold') {
        return null
    }
    return typeof c.threshold === 'number' ? c.threshold : null
}

// Sub-detector score line colors.
const SCORE_COLORS = [
    'rgba(245, 158, 11, 0.7)', // amber
    'rgba(16, 185, 129, 0.7)', // green
    'rgba(139, 92, 246, 0.7)', // purple
    'rgba(236, 72, 153, 0.7)', // pink
    'rgba(6, 182, 212, 0.7)', // cyan
]

function SimulationChart({
    result,
    detectorConfig,
}: {
    result: AlertSimulationResult
    detectorConfig?: DetectorConfig | null
}): JSX.Element {
    const theme = useChartTheme()
    const triggeredSet = new Set(result.triggered_indices)
    const threshold = getThreshold(detectorConfig)

    const subScores = result.sub_detector_scores
    const hasSubScores = !!subScores && subScores.length > 0

    // SQL insights carry no dates (their rows aren't a time axis) — label by row position.
    const labels = result.dates.length > 0 ? result.dates : result.data.map((_, i) => `Row ${i + 1}`)

    const scoreSeries: Series<SimSeriesMeta>[] = hasSubScores
        ? subScores.map((sub, i) => ({
              key: `score-${i}`,
              label: sub.type,
              data: sub.scores.map((s) => s ?? 0),
              color: SCORE_COLORS[i % SCORE_COLORS.length],
              yAxisId: 'yScore',
              meta: { isScore: true },
          }))
        : [
              {
                  key: 'score',
                  label: 'Score',
                  data: result.scores.map((s) => s ?? 0),
                  color: 'rgba(245, 158, 11, 0.8)',
                  yAxisId: 'yScore',
                  fill: { opacity: 0.1 },
                  meta: { isScore: true },
              },
          ]

    const series: Series<SimSeriesMeta>[] = [
        { key: 'value', label: 'Value', data: result.data, color: 'rgba(99, 102, 241, 0.9)', meta: { isScore: false } },
        ...scoreSeries,
    ]

    const anomalyMarkers: AnomalyMarker[] = result.data.flatMap((value, index) =>
        triggeredSet.has(index)
            ? [{ dataIndex: index, value, color: 'rgba(220, 38, 38, 0.9)', yAxisId: DEFAULT_Y_AXIS_ID }]
            : []
    )

    return (
        <div className="h-32 flex flex-col">
            <TimeSeriesLineChart<SimSeriesMeta>
                series={series}
                labels={labels}
                theme={theme}
                config={{
                    xAxis: { hide: true },
                    yAxis: [
                        { id: DEFAULT_Y_AXIS_ID, position: 'left', tickFormatter: (v) => humanFriendlyNumber(v) },
                        {
                            id: 'yScore',
                            position: 'right',
                            format: 'percentage_scaled',
                            label: 'Anomaly score',
                            // Scores are probabilities, so the axis is 0-100% whatever the data does.
                            // Floating it to the data max drops a threshold above every score: an
                            // off-plot reference line doesn't draw at all.
                            min: 0,
                            max: 1,
                        },
                    ],
                    showGrid: true,
                    legend: hasSubScores ? { show: true, position: 'bottom' } : undefined,
                    tooltip: {
                        valueFormatter: (value, entry) =>
                            (entry.series.meta as SimSeriesMeta | undefined)?.isScore
                                ? `${Math.round(value * 100)}%`
                                : humanFriendlyNumber(value),
                    },
                }}
                onError={handleChartError}
            >
                <AnomalyPointsLayer markers={anomalyMarkers} />
                {threshold != null && (
                    <ReferenceLine
                        value={threshold}
                        orientation="horizontal"
                        yAxisId="yScore"
                        variant="alert"
                        label={`Threshold ${Math.round(threshold * 100)}%`}
                        labelPosition="start"
                    />
                )}
            </TimeSeriesLineChart>
        </div>
    )
}

function SimulationStats({
    totalPoints,
    anomalyCount,
    triggeredDates,
    label,
}: {
    totalPoints: number
    anomalyCount: number
    triggeredDates: string[]
    label?: string
}): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const rate = totalPoints > 0 ? ((anomalyCount / totalPoints) * 100).toFixed(1) : '0'

    return (
        <>
            <div className="flex gap-4 text-sm">
                {label && <span className="font-semibold">{label}</span>}
                <span>
                    <strong>{totalPoints}</strong> points
                </span>
                <span>
                    <strong className="text-danger">{anomalyCount}</strong> anomalies
                </span>
                <span>
                    <strong>{rate}%</strong> anomaly rate
                </span>
            </div>
            {triggeredDates.length > 0 && (
                <div className="text-xs">
                    {triggeredDates.length <= 5 ? (
                        <div className="text-muted flex flex-wrap gap-1">
                            {triggeredDates.map((d) => (
                                <span key={d} className="bg-danger-highlight rounded px-1 py-0.5">
                                    {formatSimDate(d)}
                                </span>
                            ))}
                        </div>
                    ) : (
                        <>
                            <LemonButton type="tertiary" size="xsmall" onClick={() => setExpanded(!expanded)}>
                                {expanded ? 'Hide' : 'Show'} {triggeredDates.length} triggered dates
                            </LemonButton>
                            {expanded && (
                                <div className="text-muted mt-1 max-h-20 overflow-y-auto flex flex-wrap gap-1">
                                    {triggeredDates.map((d) => (
                                        <span key={d} className="bg-danger-highlight rounded px-1 py-0.5">
                                            {formatSimDate(d)}
                                        </span>
                                    ))}
                                </div>
                            )}
                        </>
                    )}
                </div>
            )}
        </>
    )
}

function BreakdownSimulation({
    breakdownResult,
    detectorConfig,
}: {
    breakdownResult: BreakdownSimulationResult
    detectorConfig?: DetectorConfig | null
}): JSX.Element {
    // Adapt BreakdownSimulationResult to AlertSimulationResult shape for the chart
    const chartResult: AlertSimulationResult = {
        ...breakdownResult,
        interval: null,
    }

    return (
        <div className="rounded border p-2 space-y-2">
            <div className="text-xs font-semibold text-muted truncate" title={breakdownResult.label}>
                {breakdownResult.label}
            </div>
            <SimulationChart result={chartResult} detectorConfig={detectorConfig} />
            <SimulationStats
                totalPoints={breakdownResult.total_points}
                anomalyCount={breakdownResult.anomaly_count}
                triggeredDates={breakdownResult.triggered_dates}
            />
        </div>
    )
}

export function SimulationSummary({
    result,
    detectorConfig,
}: {
    result: AlertSimulationResult
    detectorConfig?: DetectorConfig | null
}): JSX.Element {
    if (result.breakdown_results && result.breakdown_results.length > 0) {
        const rate = result.total_points > 0 ? ((result.anomaly_count / result.total_points) * 100).toFixed(1) : '0'
        return (
            <div className="rounded-lg p-3 space-y-3">
                <div className="flex gap-4 text-sm">
                    <span>
                        <strong>{result.breakdown_results.length}</strong> breakdown values
                    </span>
                    <span>
                        <strong>{result.total_points}</strong> total points
                    </span>
                    <span>
                        <strong className="text-danger">{result.anomaly_count}</strong> total anomalies
                    </span>
                    <span>
                        <strong>{rate}%</strong> anomaly rate
                    </span>
                </div>
                <div className="space-y-2 max-h-96 overflow-y-auto">
                    {result.breakdown_results.map((br) => (
                        <BreakdownSimulation key={br.label} breakdownResult={br} detectorConfig={detectorConfig} />
                    ))}
                </div>
            </div>
        )
    }

    return (
        <div className="rounded-lg p-3 space-y-2">
            <SimulationChart result={result} detectorConfig={detectorConfig} />
            <SimulationStats
                totalPoints={result.total_points}
                anomalyCount={result.anomaly_count}
                triggeredDates={result.triggered_dates}
            />
        </div>
    )
}
