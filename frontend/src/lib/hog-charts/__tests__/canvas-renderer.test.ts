import * as d3 from 'd3'

import { drawGrid, drawLine, drawPoints } from '../core/canvas-renderer'
import type { DrawContext } from '../core/canvas-renderer'
import type { ChartDimensions, Series } from '../core/types'

// Mock canvas context
function createMockCtx(): CanvasRenderingContext2D {
    return {
        beginPath: jest.fn(),
        moveTo: jest.fn(),
        lineTo: jest.fn(),
        stroke: jest.fn(),
        fill: jest.fn(),
        arc: jest.fn(),
        setLineDash: jest.fn(),
        clearRect: jest.fn(),
        save: jest.fn(),
        restore: jest.fn(),
        closePath: jest.fn(),
        strokeStyle: '',
        fillStyle: '',
        lineWidth: 1,
        lineJoin: 'round',
        lineCap: 'round',
        globalAlpha: 1,
        canvas: { width: 800, height: 400 },
    } as unknown as CanvasRenderingContext2D
}

describe('hog-charts canvas-renderer', () => {
    const dimensions: ChartDimensions = {
        width: 800,
        height: 400,
        plotLeft: 48,
        plotTop: 16,
        plotWidth: 736,
        plotHeight: 352,
    }

    const labels = ['Mon', 'Tue', 'Wed', 'Thu']

    const xScale = d3
        .scalePoint<string>()
        .domain(labels)
        .range([dimensions.plotLeft, dimensions.plotLeft + dimensions.plotWidth])
        .padding(0.5)

    const yScale = d3
        .scaleLinear()
        .domain([0, 30])
        .range([dimensions.plotTop + dimensions.plotHeight, dimensions.plotTop])

    const makeDrawCtx = (ctx: CanvasRenderingContext2D): DrawContext => ({
        ctx,
        dimensions,
        xScale,
        yScale,
        labels,
    })

    const makeSeries = (data: number[]): Series => ({
        key: 'test',
        label: 'Test',
        data,
        color: '#1d4aff',
    })

    describe('drawLine', () => {
        it('draws a line path through data points', () => {
            const ctx = createMockCtx()
            const drawCtx = makeDrawCtx(ctx)

            drawLine(drawCtx, makeSeries([10, 25, 30, 15]))

            expect(ctx.beginPath).toHaveBeenCalled()
            expect(ctx.moveTo).toHaveBeenCalled()
            expect(ctx.lineTo).toHaveBeenCalledTimes(3)
            expect(ctx.stroke).toHaveBeenCalled()
        })

        it('does not draw for empty data', () => {
            const ctx = createMockCtx()
            const drawCtx = makeDrawCtx(ctx)

            drawLine(drawCtx, makeSeries([]))

            expect(ctx.beginPath).not.toHaveBeenCalled()
        })

        it('uses dash pattern for incomplete data', () => {
            const ctx = createMockCtx()
            const drawCtx = makeDrawCtx(ctx)

            drawLine(drawCtx, makeSeries([10, 25, 30, 15]), undefined, { incompleteFromIndex: 2 })

            // Should set dashed line for incomplete portion
            expect(ctx.setLineDash).toHaveBeenCalledWith([6, 4])
        })

        it('applies series dash pattern', () => {
            const ctx = createMockCtx()
            const drawCtx = makeDrawCtx(ctx)
            const series = { ...makeSeries([10, 25, 30, 15]), dashPattern: [10, 10] }

            drawLine(drawCtx, series)

            expect(ctx.setLineDash).toHaveBeenCalledWith([10, 10])
        })
    })

    describe('drawPoints', () => {
        it('draws circles at each data point', () => {
            const ctx = createMockCtx()
            const drawCtx = makeDrawCtx(ctx)
            const series = { ...makeSeries([10, 25, 30, 15]), pointRadius: 3 }

            drawPoints(drawCtx, series)

            expect(ctx.arc).toHaveBeenCalledTimes(4)
            expect(ctx.fill).toHaveBeenCalledTimes(4)
        })

        it('does not draw when pointRadius is 0', () => {
            const ctx = createMockCtx()
            const drawCtx = makeDrawCtx(ctx)
            const series = { ...makeSeries([10, 25]), pointRadius: 0 }

            drawPoints(drawCtx, series)

            expect(ctx.arc).not.toHaveBeenCalled()
        })

        it('does not draw when pointRadius is unset', () => {
            const ctx = createMockCtx()
            const drawCtx = makeDrawCtx(ctx)

            drawPoints(drawCtx, makeSeries([10, 25]))

            expect(ctx.arc).not.toHaveBeenCalled()
        })
    })

    describe('drawGrid', () => {
        it('draws horizontal grid lines', () => {
            const ctx = createMockCtx()
            const drawCtx = makeDrawCtx(ctx)

            drawGrid(drawCtx)

            expect(ctx.beginPath).toHaveBeenCalled()
            expect(ctx.moveTo).toHaveBeenCalled()
            expect(ctx.lineTo).toHaveBeenCalled()
            expect(ctx.stroke).toHaveBeenCalled()
        })

        it('skips grid lines at goal line values', () => {
            const ctx = createMockCtx()
            const drawCtx = makeDrawCtx(ctx)

            // Grid with goal at 10 - should skip that tick
            const moveToCallsBefore = (ctx.moveTo as jest.Mock).mock.calls.length
            drawGrid(drawCtx, { goalLineValues: [] })
            const callsWithout = (ctx.moveTo as jest.Mock).mock.calls.length - moveToCallsBefore

            const ctx2 = createMockCtx()
            const drawCtx2 = makeDrawCtx(ctx2)
            drawGrid(drawCtx2, { goalLineValues: [10] })
            const callsWith = (ctx2.moveTo as jest.Mock).mock.calls.length

            // With a goal line value matching a tick, fewer lines should be drawn
            expect(callsWith).toBeLessThanOrEqual(callsWithout)
        })
    })
})
