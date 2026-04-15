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
    // Create points for the violin curve
    const points: [number, number][] = []
    const steps = 20
    const maxWidth = height / 2

    // Generate left side points (x1 to deltaX)
    for (let i = 0; i <= steps; i++) {
        const t = i / steps
        const x = x1 + (deltaX - x1) * t
        // Standard normal distribution PDF from x1 to deltaX
        const z = (t - 1) * 2 // Reduced scale factor from 2.5 to 2 for thicker tails
        const width = Math.exp(-0.5 * z * z) * maxWidth
        points.push([x, y + height / 2 - width])
    }

    // Generate right side points (deltaX to x2)
    for (let i = 0; i <= steps; i++) {
        const t = i / steps
        const x = deltaX + (x2 - deltaX) * t
        // Standard normal distribution PDF from deltaX to x2
        const z = t * 2 // Reduced scale factor from 2.5 to 2 for thicker tails
        const width = Math.exp(-0.5 * z * z) * maxWidth
        points.push([x, y + height / 2 - width])
    }

    // Generate bottom curve points (mirror of top)
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

    // Create SVG path
    return `
        M ${points[0][0]} ${points[0][1]}
        ${points.map((point) => `L ${point[0]} ${point[1]}`).join(' ')}
        Z
    `
}
