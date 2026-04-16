import { getColorVar, getSeriesColor } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { useChart } from 'lib/hooks/useChart'

import { AnomalyScoreType } from './types'

interface AnomalyChartProps {
    anomaly: AnomalyScoreType
}

export function AnomalyChart({ anomaly }: AnomalyChartProps): JSX.Element {
    const { data, dates, anomaly_index } = anomaly.data_snapshot

    const firstDate = dates?.[0]
    const lastDate = dates?.[dates.length - 1]
    const anomalyDate = anomaly_index != null ? dates?.[anomaly_index] : undefined

    const { canvasRef } = useChart({
        getConfig: () => {
            const lineColor = getSeriesColor(0)
            const anomalyColor = getColorVar('danger')
            const pointBorder = getColorVar('color-bg-primary')
            return {
                type: 'line' as const,
                data: {
                    labels: data.map((_, i) => dates?.[i] ?? String(i)),
                    datasets: [
                        {
                            data,
                            borderColor: lineColor,
                            borderWidth: 1.75,
                            pointRadius: data.map((_, i) => (i === anomaly_index ? 6 : 0)),
                            pointBackgroundColor: data.map((_, i) =>
                                i === anomaly_index ? anomalyColor : 'transparent'
                            ),
                            pointBorderColor: data.map((_, i) => (i === anomaly_index ? pointBorder : 'transparent')),
                            pointBorderWidth: data.map((_, i) => (i === anomaly_index ? 2 : 0)),
                            pointHoverRadius: data.map((_, i) => (i === anomaly_index ? 8 : 3)),
                            fill: {
                                target: 'origin',
                                above: `${lineColor}14`, // append alpha ~8% (hex 14)
                            },
                            tension: 0.35,
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
                                    const isAnomaly = item.dataIndex === anomaly_index
                                    const prefix = isAnomaly ? '⚠ anomaly  ' : 'value  '
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
        deps: [data, anomaly_index, dates],
    })

    return (
        <div className="flex w-full flex-col gap-1">
            <div className="relative h-20 w-full">
                <canvas ref={canvasRef} />
            </div>
            <div className="flex justify-between px-0.5 text-[10px] font-mono text-muted tabular-nums">
                <span>{firstDate ? dayjs(firstDate).format('MMM D') : ''}</span>
                {anomalyDate && <span className="font-semibold text-danger">{dayjs(anomalyDate).format('MMM D')}</span>}
                <span>{lastDate ? dayjs(lastDate).format('MMM D') : ''}</span>
            </div>
        </div>
    )
}
