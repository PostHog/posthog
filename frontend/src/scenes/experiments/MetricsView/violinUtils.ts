/**
 * Generates an SVG path for a violin plot visualization
 *
 * @param x1 - Left boundary of the violin
 * @param x2 - Right boundary of the violin
 * @param y - Vertical position of the violin
 * @param height - Height of the violin
 * @param deltaX - Position of the delta marker
 * @returns SVG path string
 */
export function generateViolinPath(x1: number, x2: number, y: number, height: number, deltaX: number): string {
    const points: [number, number][] = []
    const steps = 20
    const maxWidth = height / 2

    // The width follows a standard normal PDF that peaks at deltaX.
    for (let i = 0; i <= steps; i++) {
        const t = i / steps
        const x = x1 + (deltaX - x1) * t
        const z = (t - 1) * 2
        const width = Math.exp(-0.5 * z * z) * maxWidth
        points.push([x, y + height / 2 - width])
    }

    for (let i = 0; i <= steps; i++) {
        const t = i / steps
        const x = deltaX + (x2 - deltaX) * t
        const z = t * 2
        const width = Math.exp(-0.5 * z * z) * maxWidth
        points.push([x, y + height / 2 - width])
    }

    for (let i = steps; i >= 0; i--) {
        const t = i / steps
        const x = deltaX + (x2 - deltaX) * t
        const z = t * 2
        const width = Math.exp(-0.5 * z * z) * maxWidth
        points.push([x, y + height / 2 + width])
    }
    for (let i = steps; i >= 0; i--) {
        const t = i / steps
        const x = x1 + (deltaX - x1) * t
        const z = (t - 1) * 2
        const width = Math.exp(-0.5 * z * z) * maxWidth
        points.push([x, y + height / 2 + width])
    }

    return `
        M ${points[0][0]} ${points[0][1]}
        ${points.map((point) => `L ${point[0]} ${point[1]}`).join(' ')}
        Z
    `
}
