import type { ChartDimensions } from '../types'
import { clearAndPrepare } from './clearCanvas'

function makeCtx(backingWidth: number): {
    ctx: CanvasRenderingContext2D
    transforms: number[][]
} {
    const transforms: number[][] = []
    const canvas = document.createElement('canvas')
    canvas.width = backingWidth
    const ctx = {
        canvas,
        save: () => {},
        setTransform: (a: number, b: number, c: number, d: number, e: number, f: number) =>
            transforms.push([a, b, c, d, e, f]),
        clearRect: () => {},
    } as unknown as CanvasRenderingContext2D
    return { ctx, transforms }
}

function dims(width: number, height = 200): ChartDimensions {
    return { width, height, plotLeft: 48, plotTop: 16, plotWidth: width - 64, plotHeight: height - 48 }
}

describe('clearAndPrepare', () => {
    const originalDpr = window.devicePixelRatio

    afterEach(() => {
        Object.defineProperty(window, 'devicePixelRatio', { value: originalDpr, configurable: true })
    })

    it.each([
        ['resizes a backing store sized at a stale dpr', 784, 2, 1568],
        ['keeps a backing store sized at the current dpr', 1568, 2, 1568],
        ['resizes a backing store sized for an old css width', 640, 1, 784],
    ])('%s and scales the transform to match it', (_, backingWidth, dpr, expectedBackingWidth) => {
        Object.defineProperty(window, 'devicePixelRatio', { value: dpr, configurable: true })
        const { ctx, transforms } = makeCtx(backingWidth)

        clearAndPrepare(ctx, dims(784))

        expect(ctx.canvas.width).toBe(expectedBackingWidth)
        expect(transforms[0][0]).toBe(dpr)
        expect(transforms[0][3]).toBe(dpr)
    })

    it('scales each axis by its own backing ratio on a capped tall canvas', () => {
        Object.defineProperty(window, 'devicePixelRatio', { value: 2, configurable: true })
        const { ctx, transforms } = makeCtx(0)

        clearAndPrepare(ctx, dims(512, 34000))

        // `syncCanvasSize` caps a 512×34,000 grid at 493×32,767. Width rounding alone gives
        // 0.9629; applied to the height, it puts the bottom row about 30px above its DOM label.
        expect([ctx.canvas.width, ctx.canvas.height]).toEqual([493, 32767])
        expect(transforms[0][0]).toBe(493 / 512)
        expect(transforms[0][3]).toBe(32767 / 34000)
    })

    it('falls back to window.devicePixelRatio when dimensions have no width', () => {
        Object.defineProperty(window, 'devicePixelRatio', { value: 3, configurable: true })
        const { ctx, transforms } = makeCtx(0)

        clearAndPrepare(ctx, dims(0))

        expect(transforms[0][0]).toBe(3)
    })
})
