import { buildDimensions, isDrawableDimensions, sameDimensions, syncCanvasSize } from './canvas-size'
import { DEFAULT_MARGINS } from './useChartMargins'

const RECT = { width: 800, height: 400 }

describe('canvas-size', () => {
    describe('syncCanvasSize', () => {
        it.each([
            ['an integer css size', 800, 400, 1],
            ['a fractional css size', 507.328125, 311.5, 1],
            ['a fractional css size at dpr 2', 507.328125, 311.5, 2],
        ])('leaves the backing store alone on a repeat sync with %s', (_, width, height, dpr) => {
            const canvas = document.createElement('canvas')

            expect(syncCanvasSize(canvas, { width, height }, dpr)).toBe(true)
            // Assigning canvas.width/height wipes the bitmap even when the value is identical, and
            // the repaint only lands on the next animation frame — so a no-op sync must not touch
            // it, or a container that keeps reporting resizes never gets to show a drawn frame.
            expect(syncCanvasSize(canvas, { width, height }, dpr)).toBe(false)
            expect(canvas.width).toBe(Math.round(width * dpr))
            expect(canvas.style.width).toBe(`${width}px`)
        })

        it.each([
            ['the css size changes', { width: 640, height: 400 }, 1, 640],
            ['only the device pixel ratio changes', RECT, 2, 1600],
        ])('reallocates when %s', (_, rect, dpr, expectedBackingWidth) => {
            const canvas = document.createElement('canvas')
            syncCanvasSize(canvas, RECT, 1)

            expect(syncCanvasSize(canvas, rect, dpr)).toBe(true)
            expect(canvas.width).toBe(expectedBackingWidth)
        })
    })

    describe('isDrawableDimensions', () => {
        const base = buildDimensions(RECT, DEFAULT_MARGINS)

        it.each([
            ['a normal plot box', base, true],
            [
                'a height collapsed below the vertical margins',
                buildDimensions({ width: 800, height: 40 }, DEFAULT_MARGINS),
                false,
            ],
            [
                'a width narrower than the horizontal margins',
                buildDimensions({ width: 40, height: 400 }, DEFAULT_MARGINS),
                false,
            ],
            ['a non-finite width', { ...base, width: Number.NaN }, false],
            ['a non-finite plot left', { ...base, plotLeft: Number.NaN }, false],
        ])('reports %s as drawable=%s', (_, dimensions, expected) => {
            expect(isDrawableDimensions(dimensions)).toBe(expected)
        })
    })

    describe('sameDimensions', () => {
        const base = buildDimensions(RECT, DEFAULT_MARGINS)

        it.each([
            ['a rebuilt but identical box', buildDimensions(RECT, DEFAULT_MARGINS), true],
            ['a margin-only change', buildDimensions(RECT, { ...DEFAULT_MARGINS, left: 64 }), false],
            ['a size-only change', buildDimensions({ width: 799, height: 400 }, DEFAULT_MARGINS), false],
        ])('reports %s as same=%s', (_, other, expected) => {
            expect(sameDimensions(base, other)).toBe(expected)
        })
    })
})
