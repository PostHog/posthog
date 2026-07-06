import type { ChartDimensions } from '../types'

import { clearAndPrepare } from './clearCanvas'

function makeCtx(backingWidth: number): {
    ctx: CanvasRenderingContext2D
    transforms: number[][]
} {
    const transforms: number[][] = []
    const ctx = {
        canvas: { width: backingWidth } as HTMLCanvasElement,
        save: () => {},
        setTransform: (a: number, b: number, c: number, d: number, e: number, f: number) =>
            transforms.push([a, b, c, d, e, f]),
        clearRect: () => {},
    } as unknown as CanvasRenderingContext2D
    return { ctx, transforms }
}

function dims(width: number): ChartDimensions {
    return { width, height: 200, plotLeft: 48, plotTop: 16, plotWidth: width - 64, plotHeight: 152 }
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

    it('uses the backing ratio for a normal hi-dpi canvas', () => {
        Object.defineProperty(window, 'devicePixelRatio', { value: 2, configurable: true })
        const { ctx, transforms } = makeCtx(1568)

        clearAndPrepare(ctx, dims(784))

        expect(transforms[0][0]).toBe(2)
        expect(transforms[0][3]).toBe(2)
    })

    it('falls back to window.devicePixelRatio when dimensions have no width', () => {
        Object.defineProperty(window, 'devicePixelRatio', { value: 3, configurable: true })
        const { ctx, transforms } = makeCtx(0)

        clearAndPrepare(ctx, dims(0))

        expect(transforms[0][0]).toBe(3)
    })
})
