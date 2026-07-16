import { act, render } from '@testing-library/react'
import React from 'react'

import type { ChartDimensions, ChartMargins } from '../types'
import { useChartCanvas } from './useChartCanvas'

const MARGINS: ChartMargins = { left: 12, right: 12, top: 12, bottom: 12 }

function makeRect(width: number, height: number): DOMRect {
    return { x: 0, y: 0, width, height, top: 0, left: 0, right: width, bottom: height, toJSON: () => ({}) } as DOMRect
}

describe('useChartCanvas', () => {
    let rafQueue: FrameRequestCallback[]
    let currentRect: DOMRect
    let latestDimensions: ChartDimensions | null

    function Harness(): JSX.Element {
        const { wrapperRef, canvasRef, overlayCanvasRef, dimensions } = useChartCanvas({ margins: MARGINS })
        latestDimensions = dimensions
        return (
            <div ref={wrapperRef}>
                <canvas ref={canvasRef} />
                <canvas ref={overlayCanvasRef} />
            </div>
        )
    }

    // Drain queued animation frames (each tick may enqueue the next), bounded well above the
    // settle window so a runaway loop fails the test instead of hanging.
    function flushFrames(): void {
        for (let i = 0; i < 32 && rafQueue.length > 0; i++) {
            const frame = rafQueue.shift()!
            act(() => frame(0))
        }
    }

    beforeEach(() => {
        rafQueue = []
        currentRect = makeRect(800, 400)
        latestDimensions = null
        jest.spyOn(window, 'requestAnimationFrame').mockImplementation((cb: FrameRequestCallback) => rafQueue.push(cb))
        jest.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => undefined)
        jest.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(() => currentRect)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('converges to a size that settles after mount without a ResizeObserver notification', () => {
        // The global ResizeObserver mock never delivers callbacks, so the post-mount settle loop
        // is the only path that can catch a plot that shrinks after the first paint (a funnel
        // step footer appearing). Regression guard for a chart stuck painted at its mount size.
        render(<Harness />)
        expect(latestDimensions?.height).toBe(400)

        currentRect = makeRect(800, 260)
        flushFrames()

        expect(latestDimensions?.height).toBe(260)
    })

    it('does not commit a zero-area rect', () => {
        // Committing a 0×0 rect sizes the canvas to nothing and paints a permanently blank chart
        // if no later resize notification arrives — the hook must wait for a real rect instead.
        currentRect = makeRect(0, 0)
        render(<Harness />)
        flushFrames()

        expect(latestDimensions).toBeNull()
    })
})
