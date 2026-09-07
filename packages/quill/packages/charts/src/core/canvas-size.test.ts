import { dimensions, mockRect } from '../testing'
import { buildDimensions, sameDimensions, syncCanvasSize } from './canvas-size'
import { DEFAULT_MARGINS } from './hooks/useChartMargins'

/** Records assignments to an integer canvas dimension, which jsdom would otherwise apply silently. */
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

describe('canvas-size', () => {
    describe('syncCanvasSize', () => {
        it.each([
            ['an integer css size', 800, 400, 1],
            ['a fractional css size', 507.328125, 311.5, 1],
            ['a fractional css size at dpr 2', 507.328125, 311.5, 2],
        ])('leaves the backing store alone on a repeat sync with %s', (_, width, height, dpr) => {
            const canvas = document.createElement('canvas')
            syncCanvasSize(canvas, { width, height }, dpr)

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

            // The style writes sit outside the `resized` bookkeeping on purpose; folding them into
            // it would stretch a 507px bitmap over a stale CSS box.
            expect(syncCanvasSize(canvas, { width: 507.45, height: 400 }, 1)).toBe(false)
            expect(canvas.width).toBe(507)
            expect(canvas.style.width).toBe('507.45px')
        })
    })

    describe('buildDimensions', () => {
        it.each([
            { name: 'a normal container', rect: mockRect, plotWidth: 736, plotHeight: 352 },
            {
                name: 'a width narrower than the horizontal margins',
                rect: { width: 40, height: 400 },
                plotWidth: 0,
                plotHeight: 352,
            },
            {
                name: 'a height shorter than the vertical margins',
                rect: { width: 800, height: 40 },
                plotWidth: 736,
                plotHeight: 0,
            },
        ])('clamps the plot box to zero for $name', ({ rect, plotWidth, plotHeight }) => {
            // Literal expectations on purpose: this is the only independent statement of the plot box,
            // since `testing/jsdom.ts`'s shared `dimensions` fixture is itself built from this.
            expect(buildDimensions(rect, DEFAULT_MARGINS)).toEqual({
                width: rect.width,
                height: rect.height,
                plotLeft: 48,
                plotTop: 16,
                plotWidth,
                plotHeight,
            })
        })

        // `Math.max(0, NaN)` is NaN, so a non-finite rect/margin used to poison the plot size — a NaN
        // pixel range maps every point and axis tick to NaN, blanking the chart while x-only tooltips
        // still fire. Only the non-finite dimension floors to 0; the finite one keeps its real size —
        // pinning both catches a blanket floor-to-0 that would clobber a valid dimension yet still be
        // finite and non-negative. DEFAULT_MARGINS is left 48 / right 16 / top 16 / bottom 32.
        it.each([
            { name: 'a NaN height', rect: { width: 600, height: NaN }, plotWidth: 536, plotHeight: 0 },
            { name: 'an infinite height', rect: { width: 600, height: Infinity }, plotWidth: 536, plotHeight: 0 },
            { name: 'a NaN width', rect: { width: NaN, height: 400 }, plotWidth: 0, plotHeight: 352 },
        ])(
            'floors only the non-finite dimension, keeping the finite one, for $name',
            ({ rect, plotWidth, plotHeight }) => {
                const d = buildDimensions(rect, DEFAULT_MARGINS)
                expect(d.plotWidth).toBe(plotWidth)
                expect(d.plotHeight).toBe(plotHeight)
            }
        )
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
