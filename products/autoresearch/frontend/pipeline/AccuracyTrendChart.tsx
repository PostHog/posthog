import { dayjs } from 'lib/dayjs'

import { AccuracyTrend, AccuracyTrendMetric, AccuracyTrendPoint, formatTrendValue } from '../onlinePerformance'
import { trendLineStyles } from './accuracyTrendStyle'

const WIDTH = 600
const HEIGHT = 160

/** Runs of points on consecutive dates. A date a series has no value for breaks its line instead of joining across it. */
function lineRuns(points: AccuracyTrendPoint[], dateIndex: Map<string, number>): { index: number; value: number }[][] {
    const runs: { index: number; value: number }[][] = []
    let previous = -2
    for (const point of points) {
        const index = dateIndex.get(point.date) as number
        if (index !== previous + 1) {
            runs.push([])
        }
        runs[runs.length - 1].push({ index, value: point.value })
        previous = index
    }
    return runs
}

/** The y range: every value plus the reference line, padded, and kept inside 0 to 1 for metrics that are shares. */
function yDomain(trend: AccuracyTrend, metric: AccuracyTrendMetric, reference: number | null): [number, number] {
    const values = trend.series.flatMap((s) =>
        s.points.flatMap((p) => (s.role === 'champion' ? [p.value, p.low ?? p.value, p.high ?? p.value] : [p.value]))
    )
    if (reference != null) {
        values.push(reference)
    }
    const min = Math.min(...values)
    const max = Math.max(...values)
    const pad = (max - min) * 0.1 || Math.abs(max) * 0.1 || 0.01
    return [Math.max(min - pad, 0), metric === 'lift' ? max + pad : Math.min(max + pad, 1)]
}

/** One metric per prediction date, a line per model, with the AUC interval and holdout AUC in ranking mode. No chart deps, like MetricSparkline. */
export function AccuracyTrendChart({
    trend,
    metric,
    holdoutAuc,
    hoveredDate,
    onHover,
}: {
    trend: AccuracyTrend
    metric: AccuracyTrendMetric
    holdoutAuc: number | null
    hoveredDate: string | null
    onHover: (date: string | null) => void
}): JSX.Element {
    const { dates, series } = trend
    const styles = trendLineStyles(series)
    const reference = metric === 'ranking' ? holdoutAuc : null
    const [yMin, yMax] = yDomain(trend, metric, reference)
    const dateIndex = new Map(dates.map((date, index) => [date, index]))
    const x = (index: number): number => (dates.length === 1 ? WIDTH / 2 : (index * WIDTH) / (dates.length - 1))
    const y = (value: number): number => HEIGHT - ((value - yMin) / (yMax - yMin)) * HEIGHT
    const columnWidth = dates.length === 1 ? WIDTH : WIDTH / (dates.length - 1)
    const hoveredIndex = hoveredDate != null ? dateIndex.get(hoveredDate) : undefined

    const champion = series[0]
    const banded = metric === 'ranking' ? champion.points.filter((p): boolean => p.low != null && p.high != null) : []
    const band = [
        ...banded.map((p) => `${x(dateIndex.get(p.date) as number)},${y(p.high as number)}`),
        ...[...banded].reverse().map((p) => `${x(dateIndex.get(p.date) as number)},${y(p.low as number)}`),
    ].join(' ')

    return (
        <div className="space-y-1 min-w-0">
            {(banded.length > 0 || reference != null) && (
                <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs text-muted">
                    {banded.length > 0 && (
                        <span>
                            <span className="inline-block w-3 h-2 align-middle mr-1 bg-[var(--data-color-1)] opacity-20" />
                            Champion 95% interval
                        </span>
                    )}
                    {reference != null && (
                        <span>
                            <span className="inline-block w-3 align-middle mr-1 border-t border-dashed border-current" />
                            Holdout AUC {reference.toFixed(2)}
                        </span>
                    )}
                </div>
            )}
            <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-1">
                <div className="flex flex-col justify-between text-xs text-muted tabular-nums h-40 text-right">
                    <span>{formatTrendValue(metric, yMax)}</span>
                    <span>{formatTrendValue(metric, yMin)}</span>
                </div>
                <svg
                    viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
                    preserveAspectRatio="none"
                    className="w-full h-40 overflow-visible border-b border-l"
                    role="img"
                    aria-label="Accuracy over prediction dates"
                    onMouseLeave={() => onHover(null)}
                >
                    {banded.length > 0 && <polygon points={band} className="fill-[var(--data-color-1)] opacity-20" />}
                    {reference != null && (
                        <line
                            x1={0}
                            x2={WIDTH}
                            y1={y(reference)}
                            y2={y(reference)}
                            className="stroke-current text-secondary"
                            strokeDasharray="6 4"
                            vectorEffect="non-scaling-stroke"
                        />
                    )}
                    {hoveredIndex != null && (
                        <line
                            x1={x(hoveredIndex)}
                            x2={x(hoveredIndex)}
                            y1={0}
                            y2={HEIGHT}
                            className="stroke-current text-muted"
                            vectorEffect="non-scaling-stroke"
                        />
                    )}
                    {[...series].reverse().map((s, reversedIndex) => {
                        const style = styles[series.length - 1 - reversedIndex]
                        return (
                            <g key={s.key} className={style.stroke}>
                                {lineRuns(s.points, dateIndex).map((run) => (
                                    <polyline
                                        key={run[0].index}
                                        points={run.map((p) => `${x(p.index)},${y(p.value)}`).join(' ')}
                                        fill="none"
                                        strokeWidth={2}
                                        strokeDasharray={style.dash}
                                        vectorEffect="non-scaling-stroke"
                                    />
                                ))}
                                {s.points.map((p) => {
                                    const index = dateIndex.get(p.date) as number
                                    return (
                                        // A zero-length line with round caps stays a round dot when the SVG stretches.
                                        <line
                                            key={p.date}
                                            x1={x(index)}
                                            x2={x(index)}
                                            y1={y(p.value)}
                                            y2={y(p.value)}
                                            strokeWidth={s.role === 'actual' ? 4 : 6}
                                            strokeLinecap="round"
                                            vectorEffect="non-scaling-stroke"
                                        />
                                    )
                                })}
                            </g>
                        )
                    })}
                    {dates.map((date, index) => (
                        <rect
                            key={date}
                            x={x(index) - columnWidth / 2}
                            y={0}
                            width={columnWidth}
                            height={HEIGHT}
                            fill="transparent"
                            onMouseEnter={() => onHover(date)}
                        />
                    ))}
                </svg>
                <div />
                <div className="flex justify-between text-xs text-muted">
                    <span>{dayjs(dates[0]).format('MMM D')}</span>
                    {dates.length > 1 && <span>{dayjs(dates[dates.length - 1]).format('MMM D')}</span>}
                </div>
            </div>
        </div>
    )
}
