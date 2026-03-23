import annotationPlugin from 'chartjs-plugin-annotation'
import { useState } from 'react'

import { Chart } from 'lib/Chart'
import { useChart } from 'lib/hooks/useChart'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { DetectorConfig } from '~/queries/schema/schema-general'

import { AlertSimulationResult } from '../types'

Chart.register(annotationPlugin)

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

function SimulationChart({
    result,
    detectorConfig,
}: {
    result: AlertSimulationResult
    detectorConfig?: DetectorConfig | null
}): JSX.Element {
    const triggeredSet = new Set(result.triggered_indices)
    const threshold = getThreshold(detectorConfig)

    const subScores = result.sub_detector_scores
    const hasSubScores = subScores && subScores.length > 0

    // Colors for sub-detector score lines
    const scoreColors = [
        'rgba(245, 158, 11, 0.7)', // amber
        'rgba(16, 185, 129, 0.7)', // green
        'rgba(139, 92, 246, 0.7)', // purple
        'rgba(236, 72, 153, 0.7)', // pink
        'rgba(6, 182, 212, 0.7)', // cyan
    ]

    const scoreDatasets = hasSubScores
        ? subScores.map((sub, i) => ({
              label: sub.type,
              data: sub.scores.map((s) => (s != null ? s : 0)),
              borderColor: scoreColors[i % scoreColors.length],
              borderWidth: 1,
              backgroundColor: 'transparent',
              fill: false,
              pointRadius: 0,
              yAxisID: 'yScore' as const,
          }))
        : [
              {
                  label: 'Score',
                  data: result.scores.map((s) => (s != null ? s : 0)),
                  borderColor: 'rgba(245, 158, 11, 0.6)',
                  borderWidth: 1,
                  backgroundColor: 'rgba(245, 158, 11, 0.1)',
                  fill: true,
                  pointRadius: 0,
                  yAxisID: 'yScore' as const,
              },
          ]

    const { canvasRef } = useChart({
        getConfig: () => ({
            type: 'line' as const,
            data: {
                labels: result.dates,
                datasets: [
                    // Data series (left y-axis)
                    {
                        label: 'Value',
                        data: result.data,
                        borderColor: 'rgba(99, 102, 241, 0.8)',
                        borderWidth: 1.5,
                        pointRadius: result.data.map((_, i) => (triggeredSet.has(i) ? 3 : 0)),
                        pointBackgroundColor: result.data.map((_, i) =>
                            triggeredSet.has(i) ? 'rgba(220, 38, 38, 0.9)' : 'transparent'
                        ),
                        pointBorderColor: result.data.map((_, i) =>
                            triggeredSet.has(i) ? 'rgba(153, 27, 27, 1)' : 'transparent'
                        ),
                        pointBorderWidth: result.data.map((_, i) => (triggeredSet.has(i) ? 1 : 0)),
                        fill: false,
                        yAxisID: 'y',
                    },
                    ...scoreDatasets,
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: hasSubScores
                        ? {
                              display: true,
                              position: 'bottom' as const,
                              labels: {
                                  filter: (item: any) => item.text !== 'Value',
                                  boxWidth: 8,
                                  boxHeight: 2,
                                  font: { size: 9 },
                                  padding: 6,
                              },
                          }
                        : { display: false },
                    tooltip: {
                        enabled: true,
                        callbacks: {
                            label: (ctx) => {
                                if (ctx.datasetIndex === 0) {
                                    const idx = ctx.dataIndex
                                    const score = result.scores[idx]
                                    const base = `Value: ${ctx.parsed.y}`
                                    if (triggeredSet.has(idx) && score != null) {
                                        return `${base} — Anomaly: ${Math.round(score * 100)}%`
                                    }
                                    return base
                                }
                                const label = ctx.dataset.label || 'Score'
                                return `${label}: ${((ctx.parsed.y ?? 0) * 100).toFixed(0)}%`
                            },
                        },
                    },
                    annotation: threshold
                        ? {
                              annotations: {
                                  thresholdLine: {
                                      type: 'line' as const,
                                      yMin: threshold,
                                      yMax: threshold,
                                      yScaleID: 'yScore',
                                      borderColor: 'rgba(220, 38, 38, 0.5)',
                                      borderWidth: 1.5,
                                      borderDash: [4, 4],
                                      label: {
                                          content: `Threshold ${Math.round(threshold * 100)}%`,
                                          display: true,
                                          position: 'start' as const,
                                          font: { size: 9 },
                                          color: 'rgba(220, 38, 38, 0.8)',
                                          backgroundColor: 'transparent',
                                      },
                                  },
                              },
                          }
                        : undefined,
                },
                scales: {
                    x: { display: false },
                    y: {
                        display: true,
                        position: 'left' as const,
                        ticks: { maxTicksLimit: 3, font: { size: 10 } },
                        grid: { drawTicks: false },
                    },
                    yScore: {
                        display: true,
                        position: 'right' as const,
                        min: 0,
                        max: 1,
                        title: {
                            display: true,
                            text: 'Anomaly score',
                            font: { size: 9 },
                            padding: 0,
                        },
                        ticks: {
                            maxTicksLimit: 3,
                            font: { size: 9 },
                            callback: (value: string | number) => `${Math.round(Number(value) * 100)}%`,
                        },
                        grid: { display: false },
                    },
                },
                elements: { line: { tension: 0 } },
            },
        }),
        deps: [result, threshold],
    })

    return (
        <div className="h-32">
            <canvas ref={canvasRef} />
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
    const [expanded, setExpanded] = useState(false)
    const rate = result.total_points > 0 ? ((result.anomaly_count / result.total_points) * 100).toFixed(1) : '0'

    return (
        <div className="rounded-lg p-3 space-y-2">
            <SimulationChart result={result} detectorConfig={detectorConfig} />
            <div className="flex gap-4 text-sm">
                <span>
                    <strong>{result.total_points}</strong> points
                </span>
                <span>
                    <strong className="text-danger">{result.anomaly_count}</strong> anomalies
                </span>
                <span>
                    <strong>{rate}%</strong> anomaly rate
                </span>
            </div>
            {result.triggered_dates.length > 0 && (
                <div className="text-xs">
                    {result.triggered_dates.length <= 5 ? (
                        <div className="text-muted flex flex-wrap gap-1">
                            {result.triggered_dates.map((d) => (
                                <span key={d} className="bg-danger-highlight rounded px-1 py-0.5">
                                    {formatSimDate(d)}
                                </span>
                            ))}
                        </div>
                    ) : (
                        <>
                            <LemonButton type="tertiary" size="xsmall" onClick={() => setExpanded(!expanded)}>
                                {expanded ? 'Hide' : 'Show'} {result.triggered_dates.length} triggered dates
                            </LemonButton>
                            {expanded && (
                                <div className="text-muted mt-1 max-h-20 overflow-y-auto flex flex-wrap gap-1">
                                    {result.triggered_dates.map((d) => (
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
        </div>
    )
}
