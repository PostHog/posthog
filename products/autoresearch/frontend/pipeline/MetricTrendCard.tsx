import { dayjs } from 'lib/dayjs'

/** Tiny inline sparkline of a metric over prediction dates. No chart deps. */
function MetricSparkline({
    points,
    color = 'var(--success)',
    floor,
    ceil,
}: {
    points: { date: string; value: number }[]
    color?: string
    floor?: number
    ceil?: number
}): JSX.Element | null {
    if (points.length < 2) {
        return null
    }
    const width = 280
    const height = 56
    const pad = 4
    const values = points.map((p) => p.value)
    const min = Math.min(...values, ...(floor != null ? [floor] : []))
    const max = Math.max(...values, ...(ceil != null ? [ceil] : []))
    const span = max - min || 1
    const stepX = (width - pad * 2) / (points.length - 1)
    const coords = points.map((p, i) => {
        const x = pad + i * stepX
        const y = pad + (1 - (p.value - min) / span) * (height - pad * 2)
        return [x, y] as const
    })
    const line = coords.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
    const last = coords[coords.length - 1]
    return (
        <svg width={width} height={height} className="overflow-visible">
            <polyline points={line} fill="none" stroke={color} strokeWidth={2} />
            <circle cx={last[0]} cy={last[1]} r={3} fill={color} />
        </svg>
    )
}

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
