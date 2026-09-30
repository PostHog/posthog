import { dayjs } from 'lib/dayjs'

import { MetricSparkline } from './MetricSparkline'

/** A labelled sparkline card showing one realized metric's trend over prediction dates. */
export function MetricTrendCard({
    title,
    points,
    color,
    floor,
    ceil,
}: {
    title: string
    points: { date: string; value: number }[]
    color?: string
    floor?: number
    ceil?: number
}): JSX.Element | null {
    if (points.length < 2) {
        return null
    }
    const latest = points[points.length - 1]
    return (
        <div className="border rounded p-3 space-y-1 inline-block">
            <div className="text-xs font-semibold text-muted uppercase tracking-wide">{title}</div>
            <div className="text-lg font-bold">{latest.value.toFixed(3)}</div>
            <MetricSparkline points={points} color={color} floor={floor} ceil={ceil} />
            <div className="text-xs text-muted">
                {dayjs(points[0].date).format('MMM D')} to {dayjs(latest.date).format('MMM D')}
            </div>
        </div>
    )
}
