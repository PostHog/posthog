import { dayjs } from 'lib/dayjs'

import { AccuracyTrend, AccuracyTrendMetric, formatTrendValue, percentagePoints } from '../onlinePerformance'
import { TrendLineStyle, trendLineStyles } from './accuracyTrendStyle'

function LineSample({ style }: { style: TrendLineStyle }): JSX.Element {
    return (
        <svg viewBox="0 0 16 4" className={`w-4 h-1 shrink-0 ${style.stroke}`} aria-hidden>
            <line x1={0} x2={16} y1={2} y2={2} strokeWidth={2} strokeDasharray={style.dash} />
        </svg>
    )
}

/** Each line's value on one date, with the AUC interval or the gap to the actual rate, and the people checked. */
export function AccuracyTrendDatePanel({
    trend,
    metric,
    date,
}: {
    trend: AccuracyTrend
    metric: AccuracyTrendMetric
    date: string
}): JSX.Element {
    const styles = trendLineStyles(trend.series)
    const actual = trend.series.find((s) => s.role === 'actual')?.points.find((p) => p.date === date)
    const people = trend.people[date]

    return (
        <div className="w-full @3xl:w-64 shrink-0 rounded border p-3 space-y-2 text-xs">
            <div className="text-muted">Scored on {dayjs(date).format('MMM D, YYYY')}</div>
            {trend.series.map((s, index) => {
                const point = s.points.find((p) => p.date === date)
                const detail =
                    point == null
                        ? null
                        : metric === 'ranking' && point.low != null && point.high != null
                          ? `95% interval ${point.low.toFixed(3)} to ${point.high.toFixed(3)}`
                          : s.role !== 'actual' && actual != null
                            ? `${percentagePoints(point.value - actual.value)} against the actual rate`
                            : null
                return (
                    <div key={s.key} className="min-w-0">
                        <div className="flex items-center gap-2">
                            <LineSample style={styles[index]} />
                            <span className="flex-1 min-w-0 truncate">{s.label}</span>
                            <span className="font-semibold tabular-nums">
                                {point ? formatTrendValue(metric, point.value, true) : '—'}
                            </span>
                        </div>
                        {detail && <div className="text-secondary pl-6">{detail}</div>}
                    </div>
                )
            })}
            {people && (
                <div className="text-secondary border-t pt-2">
                    {people.scored.toLocaleString()} scored, {people.positive.toLocaleString()} did it
                </div>
            )}
        </div>
    )
}
