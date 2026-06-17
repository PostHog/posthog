import type { ChartDimensions } from '../types'
import { clearAndPrepare } from './clearCanvas'

const DIMENSIONS: ChartDimensions = {
    width: 800,
    height: 400,
    plotLeft: 0,
    plotTop: 0,
    plotWidth: 800,
    plotHeight: 400,
}

function fakeCtx(): CanvasRenderingContext2D {
    return {
        save: jest.fn(),
        restore: jest.fn(),
        setTransform: jest.fn(),
        clearRect: jest.fn(),
    } as unknown as CanvasRenderingContext2D
}

describe('clearAndPrepare', () => {
    it('prepares the context and returns true on a healthy canvas', () => {
        const ctx = fakeCtx()
        expect(clearAndPrepare(ctx, DIMENSIONS)).toBe(true)
        expect(ctx.save).toHaveBeenCalledTimes(1)
        expect(ctx.setTransform).toHaveBeenCalledTimes(1)
        expect(ctx.clearRect).toHaveBeenCalledWith(0, 0, 800, 400)
        // The caller is responsible for the matching restore after drawing.
        expect(ctx.restore).not.toHaveBeenCalled()
    })

    it('returns false and unwinds the save when the canvas is in an error state', () => {
        const ctx = fakeCtx()
        ;(ctx.setTransform as jest.Mock).mockImplementation(() => {
            throw new DOMException('Canvas is already in error state', 'InvalidStateError')
        })
        expect(clearAndPrepare(ctx, DIMENSIONS)).toBe(false)
        expect(ctx.save).toHaveBeenCalledTimes(1)
        // We saved before the throw, so we must restore to keep the ctx stack balanced.
        expect(ctx.restore).toHaveBeenCalledTimes(1)
    })

    it('returns false without restoring when save itself throws', () => {
        const ctx = fakeCtx()
        ;(ctx.save as jest.Mock).mockImplementation(() => {
            throw new DOMException('Canvas is already in error state', 'InvalidStateError')
        })
        expect(clearAndPrepare(ctx, DIMENSIONS)).toBe(false)
        expect(ctx.restore).not.toHaveBeenCalled()
    })

    it('swallows a throwing restore so a poisoned canvas never propagates', () => {
        const ctx = fakeCtx()
        ;(ctx.setTransform as jest.Mock).mockImplementation(() => {
            throw new DOMException('Canvas is already in error state', 'InvalidStateError')
        })
        ;(ctx.restore as jest.Mock).mockImplementation(() => {
            throw new DOMException('Canvas is already in error state', 'InvalidStateError')
        })
        expect(() => clearAndPrepare(ctx, DIMENSIONS)).not.toThrow()
        expect(clearAndPrepare(ctx, DIMENSIONS)).toBe(false)
    })
})
