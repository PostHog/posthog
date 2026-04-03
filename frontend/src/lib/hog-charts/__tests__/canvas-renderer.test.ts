import * as d3 from 'd3'

import { drawArea, drawLine, type DrawContext } from '../core/canvas-renderer'
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
        stroke: jest.fn(),
        fill: jest.fn(),
        closePath: jest.fn(),
        arc: jest.fn(),
        setLineDash: jest.fn(),
        strokeStyle: '',
        fillStyle: '',
        lineWidth: 0,
        lineJoin: '',
        lineCap: '',
        globalAlpha: 1,
    } as unknown as jest.Mocked<CanvasRenderingContext2D>
}

function makeDrawContext(ctx: CanvasRenderingContext2D, labels: string[]): DrawContext {
    const xScale = d3.scalePoint<string>().domain(labels).range([48, 784]).padding(0)
    const yScale = d3.scaleLinear().domain([0, 100]).range([368, 16])
    return { ctx, dimensions, xScale, yScale, labels }
}

/** Builds a DrawContext where specific y-values produce Infinity (simulating gaps). */
function makeDrawContextWithGaps(ctx: CanvasRenderingContext2D, labels: string[], gapValues: Set<number>): DrawContext {
    const xScale = d3.scalePoint<string>().domain(labels).range([48, 784])
    const origYScale = d3.scaleLinear().domain([0, 100]).range([368, 16])
    const patchedYScale = (v: number): number => (gapValues.has(v) ? Infinity : origYScale(v))
    Object.assign(patchedYScale, origYScale)
    return { ctx, dimensions, xScale, yScale: patchedYScale as any, labels }
}

describe('hog-charts canvas-renderer', () => {
    describe('drawLine — gap handling', () => {
        it('skips non-finite y points without breaking the path', () => {
            const ctx = mockCanvasContext()
            const labels = ['a', 'b', 'c']
            const series = makeSeries({ key: 's1', data: [10, 50, 90] })
            const drawCtx = makeDrawContextWithGaps(ctx, labels, new Set([50]))
            drawLine(drawCtx, series)
            expect(ctx.moveTo).toHaveBeenCalledTimes(1)
            expect(ctx.lineTo).toHaveBeenCalledTimes(1)
        })

        it('does not draw anything for empty data', () => {
            const ctx = mockCanvasContext()
            const series = makeSeries({ key: 's1', data: [] })
            drawLine(makeDrawContext(ctx, []), series)
            expect(ctx.beginPath).not.toHaveBeenCalled()
        })

        it('uses yValues override instead of series.data when provided', () => {
            const ctx = mockCanvasContext()
            const labels = ['a', 'b']
            const series = makeSeries({ key: 's1', data: [0, 0] })
            drawLine(makeDrawContext(ctx, labels), series, [10, 90])
            expect(ctx.moveTo).toHaveBeenCalledTimes(1)
            expect(ctx.lineTo).toHaveBeenCalledTimes(1)
        })
    })

    describe('drawArea — gap handling', () => {
        it('does not fill a segment with only a single point', () => {
            const ctx = mockCanvasContext()
            const series = makeSeries({ key: 's1', data: [50] })
            drawArea(makeDrawContext(ctx, ['a']), series)
            expect(ctx.fill).not.toHaveBeenCalled()
        })

        it('splits into separate fill calls when data has a gap', () => {
            const ctx = mockCanvasContext()
            const labels = ['a', 'b', 'c', 'd']
            const series = makeSeries({ key: 's1', data: [10, 999, 50, 80] })
            const drawCtx = makeDrawContextWithGaps(ctx, labels, new Set([999]))
            drawArea(drawCtx, series)
            // [a] is a single-point segment (skipped), [c,d] is a two-point segment (filled once)
            expect(ctx.fill).toHaveBeenCalledTimes(1)
        })

        it('fills two separate segments when a gap splits the data in the middle', () => {
            const ctx = mockCanvasContext()
            const labels = ['a', 'b', 'c', 'd', 'e']
            const series = makeSeries({ key: 's1', data: [10, 20, 999, 80, 90] })
            const drawCtx = makeDrawContextWithGaps(ctx, labels, new Set([999]))
            drawArea(drawCtx, series)
            // [a,b] and [d,e] are both two-point segments
            expect(ctx.fill).toHaveBeenCalledTimes(2)
        })

        it('does not fill when all data produces non-finite y values', () => {
            const ctx = mockCanvasContext()
            const labels = ['a', 'b']
            const series = makeSeries({ key: 's1', data: [999, 998] })
            const drawCtx = makeDrawContextWithGaps(ctx, labels, new Set([999, 998]))
            drawArea(drawCtx, series)
            expect(ctx.fill).not.toHaveBeenCalled()
        })
    })
})
