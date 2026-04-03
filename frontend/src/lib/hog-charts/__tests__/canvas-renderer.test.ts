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
        it.each([
            {
                name: 'does not draw anything for empty data',
                labels: [] as string[],
                data: [] as number[],
                gapValues: new Set<number>(),
                expectedBeginPath: 0,
                expectedMoveTo: 0,
                expectedLineTo: 0,
            },
            {
                name: 'skips non-finite y points without breaking the path',
                labels: ['a', 'b', 'c'],
                data: [10, 50, 90],
                gapValues: new Set([50]),
                expectedBeginPath: 1,
                expectedMoveTo: 1,
                expectedLineTo: 1,
            },
            {
                name: 'does not draw any path segments when all values are non-finite',
                labels: ['a', 'b'],
                data: [999, 998],
                gapValues: new Set([999, 998]),
                expectedBeginPath: 1,
                expectedMoveTo: 0,
                expectedLineTo: 0,
            },
        ])('$name', ({ labels, data, gapValues, expectedBeginPath, expectedMoveTo, expectedLineTo }) => {
            const ctx = mockCanvasContext()
            const series = makeSeries({ key: 's1', data })
            const drawCtx =
                gapValues.size > 0 ? makeDrawContextWithGaps(ctx, labels, gapValues) : makeDrawContext(ctx, labels)
            drawLine(drawCtx, series)
            expect(ctx.beginPath).toHaveBeenCalledTimes(expectedBeginPath)
            expect(ctx.moveTo).toHaveBeenCalledTimes(expectedMoveTo)
            expect(ctx.lineTo).toHaveBeenCalledTimes(expectedLineTo)
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
        it.each([
            {
                name: 'does not fill a segment with only a single point',
                labels: ['a'],
                data: [50],
                gapValues: new Set<number>(),
                expectedFillCount: 0,
            },
            {
                name: 'splits into separate fill calls when data has a gap',
                labels: ['a', 'b', 'c', 'd'],
                data: [10, 999, 50, 80],
                gapValues: new Set([999]),
                expectedFillCount: 1,
            },
            {
                name: 'fills two separate segments when a gap splits the data in the middle',
                labels: ['a', 'b', 'c', 'd', 'e'],
                data: [10, 20, 999, 80, 90],
                gapValues: new Set([999]),
                expectedFillCount: 2,
            },
            {
                name: 'does not fill when all data produces non-finite y values',
                labels: ['a', 'b'],
                data: [999, 998],
                gapValues: new Set([999, 998]),
                expectedFillCount: 0,
            },
        ])('$name', ({ labels, data, gapValues, expectedFillCount }) => {
            const ctx = mockCanvasContext()
            const series = makeSeries({ key: 's1', data })
            const drawCtx =
                gapValues.size > 0 ? makeDrawContextWithGaps(ctx, labels, gapValues) : makeDrawContext(ctx, labels)
            drawArea(drawCtx, series)
            expect(ctx.fill).toHaveBeenCalledTimes(expectedFillCount)
        })
    })
})
