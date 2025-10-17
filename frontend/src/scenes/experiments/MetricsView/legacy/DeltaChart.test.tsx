import { generateViolinPath } from './violinUtils'

/**
 * Helper function to parse SVG path string into points, optionally skipping the initial move command
 */
function parseSvgPathToPoints(path: string, skipInitialMove = false): Array<{ x: number; y: number }> {
    // Clean up the path string by removing newlines and extra spaces
    const cleanPath = path.replace(/\n/g, ' ').replace(/\s+/g, ' ').trim()
    const points: Array<{ x: number; y: number }> = []
    let firstPoint = true
    const parts = cleanPath.split(' ')

    for (let i = 0; i < parts.length; i++) {
        const part = parts[i]
        if (part === 'M' || part === 'L') {
            // These commands are followed by x,y coordinates
            const x = Number(parts[i + 1])
            const y = Number(parts[i + 2])
            if (!isNaN(x) && !isNaN(y)) {
                // Skip the first point if it's from the M command and skipInitialMove is true
                if (!(skipInitialMove && firstPoint && part === 'M')) {
                    points.push({ x, y })
                }
                firstPoint = false
            }
            i += 2 // Skip the coordinates we just processed
        }
        // Skip 'Z' as it doesn't have coordinates
    }

    return points
}

describe('generateViolinPath', () => {
    it('generates a valid SVG path string', () => {
        const x1 = 10
        const x2 = 30
        const y = 5
        const height = 10
        const deltaX = 20

        const path = generateViolinPath(x1, x2, y, height, deltaX)

        // Check that the path is a valid SVG path string
        expect(typeof path).toBe('string')
        expect(path).toContain('M') // Should start with a move command
        expect(path).toContain('L') // Should contain line commands
        expect(path).toContain('Z') // Should end with a close path command
    })

    it('generates a symmetric path', () => {
        const x1 = 0
        const x2 = 100
        const y = 50
        const height = 20
        const deltaX = 50

        const path = generateViolinPath(x1, x2, y, height, deltaX)
        const points = parseSvgPathToPoints(path, true)

        // Check vertical symmetry around deltaX, excluding points exactly at deltaX
        const leftPoints = points.filter((p) => p.x < deltaX)
        const rightPoints = points.filter((p) => p.x > deltaX)
        const centerPoints = points.filter((p) => p.x === deltaX)

        expect(leftPoints.length).toBe(rightPoints.length)
        // Verify that points at deltaX come in pairs (top and bottom of violin)
        expect(centerPoints.length % 2).toBe(0)
    })

    it('generates an asymmetric path when deltaX is not centered', () => {
        const x1 = 0
        const x2 = 100
        const y = 50
        const height = 20
        const deltaX = 30 // Asymmetric - closer to x1 than x2

        const path = generateViolinPath(x1, x2, y, height, deltaX)
        const points = parseSvgPathToPoints(path, true)

        // Check points on each side of deltaX
        const leftPoints = points.filter((p) => p.x < deltaX)
        const rightPoints = points.filter((p) => p.x > deltaX)
        const centerPoints = points.filter((p) => p.x === deltaX)

        // Should still have equal number of points on each side
        expect(leftPoints.length).toBe(rightPoints.length)
        expect(centerPoints.length % 2).toBe(0)

        // But the x-coordinates should be distributed differently
        const leftSpan = deltaX - x1
        const rightSpan = x2 - deltaX
        expect(rightSpan).toBeGreaterThan(leftSpan)

        // Check that points are distributed proportionally
        const leftStep = leftSpan / (leftPoints.length / 2) // divide by 2 because points appear in pairs (top/bottom)
        const rightStep = rightSpan / (rightPoints.length / 2)
        expect(rightStep).toBeGreaterThan(leftStep)
    })

    it('respects the height parameter', () => {
        const x1 = 0
        const x2 = 100
        const y = 50
        const height = 20
        const deltaX = 50

        const path = generateViolinPath(x1, x2, y, height, deltaX)
        const points = parseSvgPathToPoints(path, true)

        // Get all y-coordinates from the points
        const yCoords = points.map((p) => p.y)

        // Check that all y-coordinates are within the specified height range
        const minY = Math.min(...yCoords)
        const maxY = Math.max(...yCoords)

        expect(maxY - minY).toBeLessThanOrEqual(height)
        expect(minY).toBeGreaterThanOrEqual(y)
        expect(maxY).toBeLessThanOrEqual(y + height)
    })

    it('handles zero height gracefully', () => {
        const x1 = 0
        const x2 = 100
        const y = 50
        const height = 0
        const deltaX = 50

        const path = generateViolinPath(x1, x2, y, height, deltaX)

        // Should still return a valid path string
        expect(typeof path).toBe('string')
        expect(path).toContain('M')
        expect(path).toContain('Z')
    })

    it('handles equal x1 and x2 gracefully', () => {
        const x1 = 50
        const x2 = 50
        const y = 50
        const height = 20
        const deltaX = 50

        const path = generateViolinPath(x1, x2, y, height, deltaX)

        // Should still return a valid path string
        expect(typeof path).toBe('string')
        expect(path).toContain('M')
        expect(path).toContain('Z')
    })
})
