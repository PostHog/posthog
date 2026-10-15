import type { ChartDimensions } from '../types'

import { clearAndPrepare } from './clearCanvas'

function makeCtx(
    backingWidth: number,
    backingHeight = backingWidth / 4
): {
    ctx: CanvasRenderingContext2D
    transforms: number[][]
} {
    const transforms: number[][] = []
    const ctx = {
        canvas: { width: backingWidth, height: backingHeight } as HTMLCanvasElement,
        save: () => {},
        setTransform: (a: number, b: number, c: number, d: number, e: number, f: number) =>
            transforms.push([a, b, c, d, e, f]),
        clearRect: () => {},
    } as unknown as CanvasRenderingContext2D
    return { ctx, transforms }
}

function dims(width: number, height = width / 4): ChartDimensions {
    return { width, height, plotLeft: 48, plotTop: 16, plotWidth: width - 64, plotHeight: height - 48 }
}

describe('clearAndPrepare', () => {
    const originalDpr = window.devicePixelRatio

    afterEach(() => {
        Object.defineProperty(window, 'devicePixelRatio', { value: originalDpr, configurable: true })
    })

    it('scales the transform by the backing-store ratio, ignoring a mismatched window.devicePixelRatio', () => {
        // Backing sized at dpr=1 (canvas.width === css width) while the global now reports 2 — the
        // export's resize-under-device_scale_factor=2 case. The transform must follow the backing
        // (1), not the stale global (2), or every coordinate doubles and the chart magnifies/clips.
        Object.defineProperty(window, 'devicePixelRatio', { value: 2, configurable: true })
        const { ctx, transforms } = makeCtx(784)

        clearAndPrepare(ctx, dims(784))

        expect(transforms[0][0]).toBe(1)
        expect(transforms[0][3]).toBe(1)
    })

    it.each([
        { case: 'a normal hi-dpi canvas', css: [784, 196], backing: [1568, 392] },
        // `syncCanvasSize` caps a 512×34,000 grid at 493×32,767. Width rounding alone gives
        // 0.9629; applied to the height, it puts the bottom row about 30px above its DOM label.
        { case: 'a capped tall canvas', css: [512, 34000], backing: [493, 32767] },
    ])('scales each axis by its own backing ratio for $case', ({ css, backing }) => {
        Object.defineProperty(window, 'devicePixelRatio', { value: 2, configurable: true })
        const { ctx, transforms } = makeCtx(backing[0], backing[1])

        clearAndPrepare(ctx, dims(css[0], css[1]))

        expect(transforms[0][0]).toBe(backing[0] / css[0])
        expect(transforms[0][3]).toBe(backing[1] / css[1])
    })

    it('falls back to window.devicePixelRatio when dimensions have no width', () => {
        Object.defineProperty(window, 'devicePixelRatio', { value: 3, configurable: true })
        const { ctx, transforms } = makeCtx(0)

        clearAndPrepare(ctx, dims(0))

        expect(transforms[0][0]).toBe(3)
    })
})
