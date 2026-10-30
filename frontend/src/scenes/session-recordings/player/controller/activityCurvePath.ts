export interface ActivityPoint {
    x: number
    y: number
}

// The SVG path of the activity curve, closed along the bottom edge so it fills as an area. `smooth` joins the points
// with a Catmull-Rom spline as cubic Béziers, otherwise with straight segments.
export function activityAreaPath(points: ActivityPoint[], width: number, height: number, smooth: boolean): string {
    if (points.length === 0) {
        return ''
    }
    const segments: string[] = [`M 0,${height}`, `L ${points[0].x},${points[0].y}`]
    if (smooth && points.length > 2) {
        for (let i = 0; i < points.length - 1; i++) {
            const p0 = points[Math.max(i - 1, 0)]
            const p1 = points[i]
            const p2 = points[i + 1]
            const p3 = points[Math.min(i + 2, points.length - 1)]
            const c1x = p1.x + (p2.x - p0.x) / 6
            const c1y = p1.y + (p2.y - p0.y) / 6
            const c2x = p2.x - (p3.x - p1.x) / 6
            const c2y = p2.y - (p3.y - p1.y) / 6
            segments.push(`C ${c1x},${c1y} ${c2x},${c2y} ${p2.x},${p2.y}`)
        }
    } else {
        for (const point of points.slice(1)) {
            segments.push(`L ${point.x},${point.y}`)
        }
    }
    segments.push(`L ${width},${height}`, 'Z')
    return segments.join(' ')
}
