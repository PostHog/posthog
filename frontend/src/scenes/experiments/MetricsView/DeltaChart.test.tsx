import { generateViolinPath } from './DeltaChart'

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
        const lines = path
            .trim()
            .split('\n')
            .map((line: string) => line.trim())

        // Get all points from the path
        const points = lines
            .filter((line: string) => line.startsWith('L'))
            .map((line: string) => {
                const [x, y] = line.replace('L', '').trim().split(' ').map(Number)
                return { x, y }
            })

        // Check vertical symmetry around deltaX
        const leftPoints = points.filter((p: { x: number; y: number }) => p.x <= deltaX)
        const rightPoints = points.filter((p: { x: number; y: number }) => p.x > deltaX)

        expect(leftPoints.length).toBe(rightPoints.length)
    })

    it('respects the height parameter', () => {
        const x1 = 0
        const x2 = 100
        const y = 50
        const height = 20
        const deltaX = 50

        const path = generateViolinPath(x1, x2, y, height, deltaX)
        const lines = path
            .trim()
            .split('\n')
            .map((line: string) => line.trim())

        // Get all y-coordinates from the path
        const yCoords = lines
            .filter((line: string) => line.startsWith('L'))
            .map((line: string) => Number(line.replace('L', '').trim().split(' ')[1]))

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
