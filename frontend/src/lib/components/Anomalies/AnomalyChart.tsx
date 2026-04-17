import { getColorVar, getSeriesColor } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { useChart } from 'lib/hooks/useChart'

import { AnomalyScoreType } from './types'

interface AnomalyChartProps {
    anomaly: AnomalyScoreType
}

export function AnomalyChart({ anomaly }: AnomalyChartProps): JSX.Element {
    const { data, dates, anomaly_indices, scores } = anomaly.data_snapshot
    const indices = anomaly_indices ?? []
    const scoreLine = scores ?? []
    // Only bother with the score axis once there's at least one real score
    // on the sparkline; otherwise the empty right axis just adds noise.
    const hasScoreLine = scoreLine.some((s) => s != null)
    // Pick a date format that matches the insight's interval so hourly
    // points reveal HH:mm and coarser intervals stay uncluttered.
    const tooltipDateFormat =
        anomaly.interval === 'hour' ? 'MMM D, YYYY HH:mm' : anomaly.interval === 'month' ? 'MMM YYYY' : 'MMM D, YYYY'
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
            // Score line: same danger hue at ~60% alpha (`99` hex). Punchy
            // enough to read cleanly against the metric line's 8% fill at
            // any score value, subtle enough to still feel like context.
            const scoreLineColor = `${anomalyColor}99`

            const datasets: any[] = [
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
                    yAxisID: 'y',
                },
            ]
            if (hasScoreLine) {
                datasets.push({
                    label: 'score',
                    data: scoreLine,
                    borderColor: scoreLineColor,
                    borderWidth: 1.25,
                    borderDash: [3, 3],
                    pointRadius: 0,
                    pointHoverRadius: 0,
                    tension: 0,
                    spanGaps: true,
                    fill: false,
                    yAxisID: 'y2',
                })
            }

            return {
                type: 'line' as const,
                data: {
                    labels: data.map((_, i) => dates?.[i] ?? String(i)),
                    datasets,
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
                                    return dayjs(dates[idx]).format(tooltipDateFormat)
                                },
                                label: (item) => {
                                    // The secondary axis dataset gets its own tooltip
                                    // line; the primary line emits value + optional
                                    // anomaly annotation.
                                    if (item.dataset.yAxisID === 'y2') {
                                        const pct = Math.round((item.parsed.y ?? 0) * 100)
                                        return `score  ${pct}%`
                                    }
                                    const valueLine = `value  ${item.parsed.y}`
                                    const isLatest = item.dataIndex === latestIndex
                                    const isAnomaly = anomalySet.has(item.dataIndex)
                                    if (isLatest) {
                                        return [valueLine, '⚠ anomaly (latest)']
                                    }
                                    if (isAnomaly) {
                                        return [valueLine, '⚠ anomaly']
                                    }
                                    return valueLine
                                },
                            },
                        },
                    },
                    scales: {
                        x: { display: false },
                        y: { display: false, grace: '15%' },
                        // Score axis pinned to the full 0–1 range so the line's
                        // vertical position is always comparable across rows.
                        // `weight: 0` + drawing hooks off prevents Chart.js from
                        // reserving plot-width even when display is already off
                        // — otherwise hourly rows with a visible score line
                        // render ~10 px narrower than weekly rows where the
                        // line is flat at 1.0 and invisible.
                        y2: {
                            display: false,
                            position: 'right' as const,
                            min: 0,
                            max: 1,
                            weight: 0,
                            grid: { display: false, drawTicks: false },
                            ticks: { display: false },
                            border: { display: false },
                        },
                    },
                    interaction: {
                        intersect: false,
                        mode: 'index',
                    },
                },
            }
        },
        deps: [data, indices.join(','), dates, tooltipDateFormat, hasScoreLine, scoreLine.join(',')],
    })

    return (
        <div className="relative h-full w-full">
            <canvas ref={canvasRef} />
        </div>
    )
}
