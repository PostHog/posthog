/** Tiny inline sparkline of a metric over prediction dates. No chart deps. */
export function MetricSparkline({
    points,
    color = 'var(--success)',
    floor,
    ceil,
    width = 280,
    height = 56,
}: {
    points: { date: string; value: number }[]
    color?: string
    floor?: number
    ceil?: number
    width?: number
    height?: number
}): JSX.Element | null {
    if (points.length < 2) {
        return null
    }
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
