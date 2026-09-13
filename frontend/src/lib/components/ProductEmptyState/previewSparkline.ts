/**
 * SVG paths for an empty-state preview sparkline over a 100x40 viewBox: the stroked line and the
 * filled area under it. Series are hand-authored constants, so call this once at module scope.
 */
export function sparkPaths(series: number[]): { line: string; area: string } {
    const width = 100
    const height = 40
    const pad = 3
    const min = Math.min(...series)
    const max = Math.max(...series)
    const points = series.map((value, i) => {
        const x = (i / (series.length - 1)) * width
        const y = height - pad - ((value - min) / (max - min || 1)) * (height - 2 * pad)
        return `${x.toFixed(1)} ${y.toFixed(1)}`
    })
    const line = 'M ' + points.join(' L ')
    return { line, area: `${line} L ${width} ${height} L 0 ${height} Z` }
}
