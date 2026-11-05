export function Sparkline({ values }: { values: number[] }): JSX.Element {
    const width = 72
    const height = 18
    const max = Math.max(1, ...values)
    const points = values
        .map((value, index) => {
            const x = (index / Math.max(1, values.length - 1)) * (width - 2) + 1
            const y = height - 1 - (value / max) * (height - 2)
            return `${x.toFixed(1)},${y.toFixed(1)}`
        })
        .join(' ')
    return (
        <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" className="block">
            <polyline points={points} fill="none" stroke="currentColor" strokeWidth={1.5} className="text-muted" />
        </svg>
    )
}
