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

import { makeChartErrorHandler } from 'lib/charts/chartErrorHandler'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { DetectorConfig, DetectorType } from '~/queries/schema/schema-general'

import type { ForecastSimulationApi } from '../generated/api.schemas'
import { formatForecastLevel } from '../logic/forecastRules'
import { AlertSimulationResult, BreakdownSimulationResult } from '../types'

const handleChartError = makeChartErrorHandler('alerts-simulation-chart')

interface SimSeriesMeta {
    isScore: boolean
}

/** Format a date string compactly: "Mar 16, 11:00" or "Mar 16" if midnight. */
function formatSimDate(dateStr: string): string {
    // dayjs reads a date-only label as a local calendar day. `new Date()` would read it as
    // UTC midnight, which shows the previous day to anyone west of UTC.
    const d = dayjs(dateStr)
    if (!d.isValid()) {
        return dateStr
    }
    if (d.hour() === 0 && d.minute() === 0) {
        return d.format('MMM D')
    }
    return d.format('MMM D, HH:mm')
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
    return typeof c.threshold === 'number' && !Number.isNaN(c.threshold) ? c.threshold : null
}

// Sub-detector score line colors.
const SCORE_COLORS = [
    'rgba(245, 158, 11, 0.7)', // amber
    'rgba(16, 185, 129, 0.7)', // green
    'rgba(139, 92, 246, 0.7)', // purple
    'rgba(236, 72, 153, 0.7)', // pink
    'rgba(6, 182, 212, 0.7)', // cyan
]

function getForecastSeries(forecast: ForecastSimulationApi | undefined): Series<SimSeriesMeta>[] {
    if (!forecast) {
        return []
    }
    return [
        {
            key: 'forecast-range',
            label: 'Forecast range',
            data: forecast.upper.map((v) => v ?? NaN),
            color: 'rgba(99, 102, 241, 0.9)',
            fill: { opacity: 0.15, lowerData: forecast.lower.map((v) => v ?? NaN) },
            visibility: { tooltip: false },
            meta: { isScore: false },
        },
        {
            key: 'forecast-expected',
            label: 'Expected',
            data: forecast.expected.map((v) => v ?? NaN),
            color: 'rgba(107, 114, 128, 0.9)',
            stroke: { width: 1.5, pattern: [4, 4] },
            meta: { isScore: false },
        },
    ]
}

function SimulationChart({
    result,
    detectorConfig,
}: {
    result: AlertSimulationResult
    detectorConfig?: DetectorConfig | null
}): JSX.Element {
    const theme = useChartTheme()
    const triggeredSet = new Set(result.triggered_indices)
    // The AI and forecast detectors have no score, so their previews plot the values and mark the fired points.
    const hasScore = detectorConfig?.type !== DetectorType.LLM && detectorConfig?.type !== DetectorType.FORECAST
    const threshold = hasScore ? getThreshold(detectorConfig) : null

    const subScores = result.sub_detector_scores
    const hasSubScores = !!subScores && subScores.length > 0

    // SQL insights carry no dates (their rows aren't a time axis) — label by row position.
    const labels = result.dates.length > 0 ? result.dates : result.data.map((_, i) => `Row ${i + 1}`)

    const scoreSeries: Series<SimSeriesMeta>[] = hasSubScores
        ? subScores.map((sub, i) => ({
              key: `score-${i}`,
              label: sub.type,
              data: sub.scores.map((s) => s ?? NaN),
              color: SCORE_COLORS[i % SCORE_COLORS.length],
              yAxisId: 'yScore',
              meta: { isScore: true },
          }))
        : !hasScore
          ? []
          : [
                {
                    key: 'score',
                    label: 'Score',
                    data: result.scores.map((s) => s ?? NaN),
                    color: 'rgba(245, 158, 11, 0.8)',
                    yAxisId: 'yScore',
                    fill: { opacity: 0.1 },
                    meta: { isScore: true },
                },
            ]

    const series: Series<SimSeriesMeta>[] = [
        ...getForecastSeries(result.forecast),
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
                        ...(!hasScore
                            ? []
                            : [
                                  {
                                      id: 'yScore',
                                      position: 'right' as const,
                                      format: 'percentage_scaled' as const,
                                      label: 'Anomaly score',
                                      // Floating it to the data max drops a threshold above every score: an
                                      // off-plot reference line doesn't draw at all.
                                      min: 0,
                                      max: 1,
                                  },
                              ]),
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

function ForecastNote({ result }: { result: AlertSimulationResult }): JSX.Element | null {
    const forecast = result.forecast
    if (!forecast) {
        return null
    }
    const scored = forecast.expected.filter((v) => v != null).length
    return (
        <div className="text-xs text-muted">
            {scored === 0
                ? 'No point had the 30 earlier values a forecast needs. Pick a longer range to preview this alert.'
                : `${scored} of ${result.data.length} points had the 30 earlier values a forecast needs. The shaded range runs from the ${formatForecastLevel(forecast.lower_quantile)} to the ${formatForecastLevel(forecast.upper_quantile)} of each forecast.`}
        </div>
    )
}

/** The AI preview is one live check of the latest point, so it shows that verdict instead of an anomaly rate. */
function LLMVerdict({ result }: { result: AlertSimulationResult }): JSX.Element {
    const fires = result.triggered_indices.length > 0
    const latestDate = result.dates.length > 0 ? formatSimDate(result.dates[result.dates.length - 1]) : null
    return (
        <div className="space-y-1 text-sm">
            <div>
                <strong className={fires ? 'text-danger' : undefined}>{fires ? 'Would fire' : 'Would not fire'}</strong>
                {latestDate ? ` on the latest point (${latestDate})` : ' on the latest point'}
                {fires && result.kind && result.kind !== 'none' ? ` · ${result.kind.replaceAll('_', ' ')}` : null}
            </div>
            {result.rationale ? <div className="text-muted">{result.rationale}</div> : null}
        </div>
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
            <ForecastNote result={chartResult} />
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

    if (detectorConfig?.type === DetectorType.LLM) {
        return (
            <div className="rounded-lg p-3 space-y-2">
                <SimulationChart result={result} detectorConfig={detectorConfig} />
                <LLMVerdict result={result} />
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
            <ForecastNote result={result} />
        </div>
    )
}
