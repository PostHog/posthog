import * as d3 from 'd3'

import {
    type BarRect,
    drawBarHighlight,
    drawBars,
    type DrawContext,
    traceRoundedBarPath,
} from '../core/canvas-renderer'
import type { ChartDimensions, Series } from '../core/types'

const dimensions: ChartDimensions = {
    width: 800,
    height: 400,
    plotLeft: 48,
    plotTop: 16,
    plotWidth: 736,
    plotHeight: 352,
}

function makeSeries(overrides: Partial<Series> & { key: string; data: number[] }): Series {
    return { label: overrides.key, color: '#f00', ...overrides }
}

function mockCanvasContext(): jest.Mocked<CanvasRenderingContext2D> {
    return {
        beginPath: jest.fn(),
        moveTo: jest.fn(),
        lineTo: jest.fn(),
        quadraticCurveTo: jest.fn(),
        stroke: jest.fn(),
        fill: jest.fn(),
        closePath: jest.fn(),
        setLineDash: jest.fn(),
        createPattern: jest.fn(() => ({}) as CanvasPattern),
        strokeStyle: '',
        fillStyle: '',
        lineWidth: 0,
    } as unknown as jest.Mocked<CanvasRenderingContext2D>
}

function makeDrawContext(ctx: CanvasRenderingContext2D, labels: string[]): DrawContext {
    const xScale = (label: string): number | undefined => {
        const idx = labels.indexOf(label)
        return idx < 0 ? undefined : 100 + idx * 60
    }
    const yScale = d3.scaleLinear().domain([0, 100]).range([368, 16])
    return { ctx, dimensions, xScale, yScale, labels }
}

const SQUARE: BarRect = { x: 100, y: 100, width: 50, height: 80, corners: {} }

describe('hog-charts canvas-renderer (bars)', () => {
    describe('traceRoundedBarPath', () => {
        it('emits a closed rectangular path with no rounding when no corners are flagged', () => {
            const ctx = mockCanvasContext()
            traceRoundedBarPath(ctx, 0, 0, 100, 50, 8, {})
            expect(ctx.quadraticCurveTo).not.toHaveBeenCalled()
            expect(ctx.closePath).toHaveBeenCalledTimes(1)
        })

        it('emits a quadraticCurveTo for each rounded corner', () => {
            const ctx = mockCanvasContext()
            traceRoundedBarPath(ctx, 0, 0, 100, 50, 8, { topLeft: true, topRight: true })
            expect(ctx.quadraticCurveTo).toHaveBeenCalledTimes(2)
        })

        it('clamps the radius to half the smaller dimension', () => {
            // With width 4 and a requested radius of 20, each rounded corner consumes radius 2
            // — we just verify it doesn't throw and still emits the curves.
            const ctx = mockCanvasContext()
            traceRoundedBarPath(ctx, 0, 0, 4, 50, 20, {
                topLeft: true,
                topRight: true,
                bottomLeft: true,
                bottomRight: true,
            })
            expect(ctx.quadraticCurveTo).toHaveBeenCalledTimes(4)
        })

        it('still closes the path on a zero-height rectangle', () => {
            const ctx = mockCanvasContext()
            traceRoundedBarPath(ctx, 0, 0, 100, 0, 8, { topLeft: true })
            expect(ctx.closePath).toHaveBeenCalledTimes(1)
        })
    })

    describe('drawBars', () => {
        it('does nothing when given no bars', () => {
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a', 'b'])
            drawBars(drawCtx, makeSeries({ key: 's', data: [1, 2] }), [])
            expect(ctx.fill).not.toHaveBeenCalled()
        })

        it('skips bars with zero or negative dimensions', () => {
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a', 'b'])
            drawBars(drawCtx, makeSeries({ key: 's', data: [1, 2] }), [
                { x: 0, y: 0, width: 0, height: 50, corners: {} },
                { x: 0, y: 0, width: -5, height: 50, corners: {} },
                { x: 0, y: 0, width: 50, height: 0, corners: {} },
            ])
            expect(ctx.fill).not.toHaveBeenCalled()
        })

        it('fills each non-empty bar exactly once', () => {
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a', 'b', 'c'])
            const series = makeSeries({ key: 's', data: [1, 2, 3] })
            const bars: BarRect[] = [
                { ...SQUARE, x: 0 },
                { ...SQUARE, x: 60 },
                { ...SQUARE, x: 120 },
            ]
            drawBars(drawCtx, series, bars)
            expect(ctx.fill).toHaveBeenCalledTimes(3)
        })

        it('sets the series color as fillStyle for non-dashed bars', () => {
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a'])
            const series = makeSeries({ key: 's', data: [1], color: '#abcdef' })
            drawBars(drawCtx, series, [SQUARE])
            expect(ctx.fillStyle).toBe('#abcdef')
        })

        it('fills all bars when partial fromIndex is set (some hatched, some solid)', () => {
            // The hatch pattern cache is module-level keyed by color; we verify the bar count
            // rather than whether createPattern was invoked, since prior tests may have warmed the cache.
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a', 'b', 'c'])
            const series = makeSeries({
                key: 's',
                data: [1, 2, 3],
                color: '#aabbcc',
                stroke: { partial: { fromIndex: 1 } },
            })
            drawBars(drawCtx, series, [
                { ...SQUARE, x: 0 },
                { ...SQUARE, x: 60 },
                { ...SQUARE, x: 120 },
            ])
            expect(ctx.fill).toHaveBeenCalledTimes(3)
        })

        it('fills all bars when partial toIndex is set', () => {
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a', 'b', 'c'])
            const series = makeSeries({
                key: 's',
                data: [1, 2, 3],
                color: '#ccbbaa',
                stroke: { partial: { toIndex: 0 } },
            })
            drawBars(drawCtx, series, [
                { ...SQUARE, x: 0 },
                { ...SQUARE, x: 60 },
                { ...SQUARE, x: 120 },
            ])
            expect(ctx.fill).toHaveBeenCalledTimes(3)
        })

        it('respects the cornerRadius option', () => {
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a'])
            const series = makeSeries({ key: 's', data: [1] })
            drawBars(drawCtx, series, [{ ...SQUARE, corners: { topLeft: true, topRight: true } }], { cornerRadius: 12 })
            // 2 rounded corners → 2 quadraticCurveTo calls
            expect(ctx.quadraticCurveTo).toHaveBeenCalledTimes(2)
        })

        it('does not invoke createPattern when no partial dashing is set', () => {
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a'])
            drawBars(drawCtx, makeSeries({ key: 's', data: [1] }), [SQUARE])
            expect(ctx.createPattern).not.toHaveBeenCalled()
        })
    })

    describe('drawBarHighlight', () => {
        it('strokes a single rectangle', () => {
            const ctx = mockCanvasContext()
            drawBarHighlight(ctx, SQUARE, '#000')
            expect(ctx.stroke).toHaveBeenCalledTimes(1)
        })

        it('does nothing on a zero-width bar', () => {
            const ctx = mockCanvasContext()
            drawBarHighlight(ctx, { ...SQUARE, width: 0 }, '#000')
            expect(ctx.stroke).not.toHaveBeenCalled()
        })

        it('uses the provided color as strokeStyle', () => {
            const ctx = mockCanvasContext()
            drawBarHighlight(ctx, SQUARE, '#abcabc')
            expect(ctx.strokeStyle).toBe('#abcabc')
        })

        it('clears the dash pattern before stroking', () => {
            const ctx = mockCanvasContext()
            drawBarHighlight(ctx, SQUARE, '#000')
            expect(ctx.setLineDash).toHaveBeenCalledWith([])
        })
    })
})
