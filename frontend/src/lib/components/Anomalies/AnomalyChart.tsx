import { getColorVar, getSeriesColor } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { useChart } from 'lib/hooks/useChart'

import { AnomalyScoreType } from './types'

interface AnomalyChartProps {
    anomaly: AnomalyScoreType
}

export function AnomalyChart({ anomaly }: AnomalyChartProps): JSX.Element {
    const { data, dates, anomaly_indices } = anomaly.data_snapshot
    const indices = anomaly_indices ?? []
    // The most recent anomaly is the last entry (indices are sorted asc).
    // Drawn bright red and slightly larger so a scanner's eye lands on it
    // first; older anomalies on the same series are rendered muted for
    // context without competing for attention.
    const latestIndex = indices.length ? indices[indices.length - 1] : null
    const anomalySet = new Set(indices)

    const { canvasRef } = useChart({
        getConfig: () => {
            const lineColor = getSeriesColor(0)
            const anomalyColor = getColorVar('danger')
            const pointBorder = getColorVar('color-bg-primary')
            // Muted shade for past anomalies: same danger hue at ~45% alpha.
            const pastAnomalyColor = `${anomalyColor}73`
            return {
                type: 'line' as const,
                data: {
                    labels: data.map((_, i) => dates?.[i] ?? String(i)),
                    datasets: [
                        {
                            data,
                            borderColor: lineColor,
                            borderWidth: 1.75,
                            pointRadius: data.map((_, i) => (i === latestIndex ? 6 : anomalySet.has(i) ? 4 : 0)),
                            pointBackgroundColor: data.map((_, i) =>
                                i === latestIndex ? anomalyColor : anomalySet.has(i) ? pastAnomalyColor : 'transparent'
                            ),
                            pointBorderColor: data.map((_, i) => (anomalySet.has(i) ? pointBorder : 'transparent')),
                            pointBorderWidth: data.map((_, i) => (i === latestIndex ? 2 : anomalySet.has(i) ? 1 : 0)),
                            pointHoverRadius: data.map((_, i) => (i === latestIndex ? 8 : anomalySet.has(i) ? 6 : 3)),
                            fill: {
                                target: 'origin',
                                above: `${lineColor}14`, // append alpha ~8% (hex 14)
                            },
                            tension: 0,
                            spanGaps: true,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            enabled: true,
                            intersect: false,
                            mode: 'index',
                            callbacks: {
                                title: (items) => {
                                    const idx = items[0]?.dataIndex
                                    if (idx == null || !dates?.[idx]) {
                                        return ''
                                    }
                                    return dayjs(dates[idx]).format('MMM D, YYYY')
                                },
                                label: (item) => {
                                    const isAnomaly = anomalySet.has(item.dataIndex)
                                    const isLatest = item.dataIndex === latestIndex
                                    const prefix = isLatest
                                        ? '⚠ anomaly (latest)  '
                                        : isAnomaly
                                          ? '⚠ anomaly  '
                                          : 'value  '
                                    return `${prefix}${item.parsed.y}`
                                },
                            },
                        },
                    },
                    scales: {
                        x: { display: false },
                        y: { display: false, grace: '15%' },
                    },
                    interaction: {
                        intersect: false,
                        mode: 'index',
                    },
                },
            }
        },
        deps: [data, indices.join(','), dates],
    })

    return (
        <div className="relative h-full w-full">
            <canvas ref={canvasRef} />
        </div>
    )
}
