import { dimensions, mockRect } from '../../testing'
import { buildDimensions, sameDimensions, syncCanvasSize } from './canvas-size'
import { DEFAULT_MARGINS } from './useChartMargins'

describe('canvas-size', () => {
    describe('syncCanvasSize', () => {
        it.each([
            ['an integer css size', 800, 400, 1],
            ['a fractional css size', 507.328125, 311.5, 1],
            ['a fractional css size at dpr 2', 507.328125, 311.5, 2],
        ])('leaves the backing store alone on a repeat sync with %s', (_, width, height, dpr) => {
            const canvas = document.createElement('canvas')
            syncCanvasSize(canvas, { width, height }, dpr)

            // Assigning canvas.width/height wipes the bitmap even when the value is identical, and
            // the repaint only lands on the next animation frame — so a no-op sync must not write
            // at all, or a container that keeps reporting resizes never shows a drawn frame.
            const writes: string[] = []
            trackWrites(canvas, 'width', writes)
            trackWrites(canvas, 'height', writes)

            expect(syncCanvasSize(canvas, { width, height }, dpr)).toBe(false)
            expect(writes).toEqual([])
            expect(canvas.width).toBe(Math.round(width * dpr))
            expect(canvas.height).toBe(Math.round(height * dpr))
            expect(canvas.style.width).toBe(`${width}px`)
            expect(canvas.style.height).toBe(`${height}px`)
        })

        it.each([
            ['the css width changes', { width: 640, height: 400 }, 1, 640, 400],
            ['the css height changes', { width: 800, height: 300 }, 1, 800, 300],
            ['only the device pixel ratio changes', { width: 800, height: 400 }, 2, 1600, 800],
        ])('reallocates when %s', (_, rect, dpr, expectedWidth, expectedHeight) => {
            const canvas = document.createElement('canvas')
            syncCanvasSize(canvas, { width: 800, height: 400 }, 1)

            expect(syncCanvasSize(canvas, rect, dpr)).toBe(true)
            expect(canvas.width).toBe(expectedWidth)
            expect(canvas.height).toBe(expectedHeight)
        })

        it('still updates the css size when a sub-pixel change rounds to the same backing store', () => {
            const canvas = document.createElement('canvas')
            syncCanvasSize(canvas, { width: 507.4, height: 400 }, 1)

            // Both round to a 507px backing store, so there is nothing to reallocate — but the CSS
            // size still moved. The style writes sit outside the `resized` bookkeeping on purpose;
            // folding them into it would stretch a 507px bitmap over a stale CSS box.
            expect(syncCanvasSize(canvas, { width: 507.45, height: 400 }, 1)).toBe(false)
            expect(canvas.width).toBe(507)
            expect(canvas.style.width).toBe('507.45px')
        })
    })

    describe('sameDimensions', () => {
        it.each([
            { name: 'a rebuilt but identical box', other: buildDimensions(mockRect, DEFAULT_MARGINS), same: true },
            {
                name: 'a margin-only change',
                other: buildDimensions(mockRect, { ...DEFAULT_MARGINS, left: 64 }),
                same: false,
            },
            {
                name: 'a size-only change',
                other: buildDimensions({ width: 799, height: 400 }, DEFAULT_MARGINS),
                same: false,
            },
        ])('reports $name as same=$same', ({ other, same }) => {
            expect(sameDimensions(dimensions, other)).toBe(same)
        })
    })
})

/** Records assignments to an integer canvas dimension so a test can assert none happened. */
function trackWrites(canvas: HTMLCanvasElement, prop: 'width' | 'height', writes: string[]): void {
    let value = canvas[prop]
    Object.defineProperty(canvas, prop, {
        configurable: true,
        get: () => value,
        set: (next: number) => {
            writes.push(`${prop}=${next}`)
            value = next
        },
    })
}
