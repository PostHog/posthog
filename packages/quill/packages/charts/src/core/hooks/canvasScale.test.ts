import { effectiveCanvasScale } from './canvasScale'

const MAX_CANVAS_DIMENSION = 16384

describe('effectiveCanvasScale', () => {
    it('returns dpr unchanged for ordinary sizes', () => {
        expect(effectiveCanvasScale(800, 400, 2)).toBe(2)
        expect(effectiveCanvasScale(1920, 1080, 1)).toBe(1)
    })

    it('falls back to 1 for a non-positive dpr', () => {
        expect(effectiveCanvasScale(800, 400, 0)).toBe(1)
        expect(effectiveCanvasScale(800, 400, -3)).toBe(1)
    })

    it('returns the base scale for a zero-sized box', () => {
        expect(effectiveCanvasScale(0, 400, 2)).toBe(2)
        expect(effectiveCanvasScale(800, 0, 2)).toBe(2)
    })

    it('clamps so neither backing dimension exceeds the per-dimension limit', () => {
        // 9000px wide at dpr 2 would back a 18000px bitmap — past the 16384 cap.
        const scale = effectiveCanvasScale(9000, 400, 2)
        expect(scale).toBeLessThan(2)
        expect(9000 * scale).toBeLessThanOrEqual(MAX_CANVAS_DIMENSION)
        expect(400 * scale).toBeLessThanOrEqual(MAX_CANVAS_DIMENSION)
    })

    it('clamps the limiting dimension when height is the larger side', () => {
        const scale = effectiveCanvasScale(400, 12000, 3)
        expect(400 * scale).toBeLessThanOrEqual(MAX_CANVAS_DIMENSION)
        expect(12000 * scale).toBeLessThanOrEqual(MAX_CANVAS_DIMENSION)
    })

    it('clamps total area even when each side is within the per-dimension limit', () => {
        // 15000 × 15000 each fit under 16384, but the area at dpr 2 blows past 16384².
        const scale = effectiveCanvasScale(15000, 15000, 2)
        const area = 15000 * scale * (15000 * scale)
        expect(area).toBeLessThanOrEqual(MAX_CANVAS_DIMENSION * MAX_CANVAS_DIMENSION + 1)
    })

    it('never returns a non-positive scale', () => {
        expect(effectiveCanvasScale(1_000_000, 1_000_000, 4)).toBeGreaterThan(0)
    })

    it('never upscales past the requested dpr', () => {
        expect(effectiveCanvasScale(100, 100, 2)).toBeLessThanOrEqual(2)
    })
})
