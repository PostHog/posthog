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

/** Collects dash-pattern argument of each setLineDash call (ignoring the final [] reset). */
function dashCalls(ctx: jest.Mocked<CanvasRenderingContext2D>): number[][] {
    return ctx.setLineDash.mock.calls.map(([p]: [number[]]) => p)
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

    describe('drawLine — partial dashing (dashedFromIndex / dashedToIndex)', () => {
        it('uses a single solid stroke when neither index is set', () => {
            const ctx = mockCanvasContext()
            const series = makeSeries({ key: 's1', data: [10, 20, 30] })
            drawLine(makeDrawContext(ctx, ['a', 'b', 'c']), series)
            expect(ctx.beginPath).toHaveBeenCalledTimes(1)
            expect(ctx.stroke).toHaveBeenCalledTimes(1)
            expect(dashCalls(ctx)).toEqual([[], []])
        })

        it('preserves series.dashPattern on the fast path', () => {
            const ctx = mockCanvasContext()
            const series = makeSeries({ key: 's1', data: [10, 20, 30], dashPattern: [4, 4] })
            drawLine(makeDrawContext(ctx, ['a', 'b', 'c']), series)
            expect(dashCalls(ctx)).toEqual([[4, 4], []])
        })

        describe('dashedFromIndex', () => {
            it('splits into solid + dashed subpaths sharing the boundary point', () => {
                const ctx = mockCanvasContext()
                const series = makeSeries({
                    key: 's1',
                    data: [10, 20, 30, 40, 50],
                    dashedFromIndex: 3,
                })
                drawLine(makeDrawContext(ctx, ['a', 'b', 'c', 'd', 'e']), series)
                // Solid [0..2], dashed [2..4]. Each subpath calls moveTo once, lineTo per extra point.
                expect(ctx.beginPath).toHaveBeenCalledTimes(2)
                expect(ctx.stroke).toHaveBeenCalledTimes(2)
                expect(ctx.moveTo).toHaveBeenCalledTimes(2)
                // Solid 0..2: 2 lineTos. Dashed 2..4: 2 lineTos.
                expect(ctx.lineTo).toHaveBeenCalledTimes(4)
                expect(dashCalls(ctx)).toEqual([[], [10, 10], []])
            })

            it('dashes the projection tail (incomplete-data use case)', () => {
                const ctx = mockCanvasContext()
                const data = [10, 20, 30, 40, 50]
                const series = makeSeries({ key: 's1', data, dashedFromIndex: data.length - 1 })
                drawLine(makeDrawContext(ctx, ['a', 'b', 'c', 'd', 'e']), series)
                // Solid [0..3], dashed [3..4] (just the last segment).
                expect(ctx.beginPath).toHaveBeenCalledTimes(2)
                expect(dashCalls(ctx)).toEqual([[], [10, 10], []])
            })

            it('dashes the entire line when dashedFromIndex === 0', () => {
                const ctx = mockCanvasContext()
                const series = makeSeries({ key: 's1', data: [10, 20, 30], dashedFromIndex: 0 })
                drawLine(makeDrawContext(ctx, ['a', 'b', 'c']), series)
                expect(ctx.beginPath).toHaveBeenCalledTimes(1)
                expect(dashCalls(ctx)).toEqual([[10, 10], []])
            })

            it('treats dashedFromIndex >= length as unset', () => {
                const ctx = mockCanvasContext()
                const series = makeSeries({ key: 's1', data: [10, 20, 30], dashedFromIndex: 99 })
                drawLine(makeDrawContext(ctx, ['a', 'b', 'c']), series)
                expect(ctx.beginPath).toHaveBeenCalledTimes(1)
                expect(dashCalls(ctx)).toEqual([[], []])
            })

            it('clamps negative dashedFromIndex to 0 (entire line dashed)', () => {
                const ctx = mockCanvasContext()
                const series = makeSeries({ key: 's1', data: [10, 20, 30], dashedFromIndex: -5 })
                drawLine(makeDrawContext(ctx, ['a', 'b', 'c']), series)
                expect(ctx.beginPath).toHaveBeenCalledTimes(1)
                expect(dashCalls(ctx)).toEqual([[10, 10], []])
            })
        })

        describe('dashedToIndex', () => {
            it('splits into dashed + solid subpaths', () => {
                const ctx = mockCanvasContext()
                const series = makeSeries({
                    key: 's1',
                    data: [10, 20, 30, 40, 50],
                    dashedToIndex: 1,
                })
                drawLine(makeDrawContext(ctx, ['a', 'b', 'c', 'd', 'e']), series)
                // Dashed [0..1], solid [1..4].
                expect(ctx.beginPath).toHaveBeenCalledTimes(2)
                expect(dashCalls(ctx)).toEqual([[10, 10], [], []])
            })

            it('dashes the entire line when dashedToIndex === length - 1', () => {
                const ctx = mockCanvasContext()
                const series = makeSeries({ key: 's1', data: [10, 20, 30], dashedToIndex: 2 })
                drawLine(makeDrawContext(ctx, ['a', 'b', 'c']), series)
                expect(ctx.beginPath).toHaveBeenCalledTimes(1)
                expect(dashCalls(ctx)).toEqual([[10, 10], []])
            })

            it('treats dashedToIndex < 0 as unset', () => {
                const ctx = mockCanvasContext()
                const series = makeSeries({ key: 's1', data: [10, 20, 30], dashedToIndex: -5 })
                drawLine(makeDrawContext(ctx, ['a', 'b', 'c']), series)
                expect(ctx.beginPath).toHaveBeenCalledTimes(1)
                expect(dashCalls(ctx)).toEqual([[], []])
            })

            it('clamps dashedToIndex beyond length to the last index (entire line dashed)', () => {
                const ctx = mockCanvasContext()
                const series = makeSeries({ key: 's1', data: [10, 20, 30], dashedToIndex: 99 })
                drawLine(makeDrawContext(ctx, ['a', 'b', 'c']), series)
                expect(ctx.beginPath).toHaveBeenCalledTimes(1)
                expect(dashCalls(ctx)).toEqual([[10, 10], []])
            })
        })

        describe('both ends dashed', () => {
            it('splits into dashed + solid + dashed when there is a solid middle', () => {
                const ctx = mockCanvasContext()
                const series = makeSeries({
                    key: 's1',
                    data: [10, 20, 30, 40, 50, 60, 70],
                    dashedToIndex: 1,
                    dashedFromIndex: 5,
                })
                drawLine(makeDrawContext(ctx, ['a', 'b', 'c', 'd', 'e', 'f', 'g']), series)
                expect(ctx.beginPath).toHaveBeenCalledTimes(3)
                expect(ctx.stroke).toHaveBeenCalledTimes(3)
                expect(dashCalls(ctx)).toEqual([[10, 10], [], [10, 10], []])
            })

            it('dashes the entire line when the two dashed ends meet (to === from - 1)', () => {
                const ctx = mockCanvasContext()
                const series = makeSeries({
                    key: 's1',
                    data: [10, 20, 30, 40, 50],
                    dashedToIndex: 2,
                    dashedFromIndex: 3,
                })
                drawLine(makeDrawContext(ctx, ['a', 'b', 'c', 'd', 'e']), series)
                expect(ctx.beginPath).toHaveBeenCalledTimes(1)
                expect(dashCalls(ctx)).toEqual([[10, 10], []])
            })

            it('dashes the entire line when the two dashed ends overlap (to > from - 1)', () => {
                const ctx = mockCanvasContext()
                const series = makeSeries({
                    key: 's1',
                    data: [10, 20, 30, 40, 50],
                    dashedToIndex: 3,
                    dashedFromIndex: 2,
                })
                drawLine(makeDrawContext(ctx, ['a', 'b', 'c', 'd', 'e']), series)
                expect(ctx.beginPath).toHaveBeenCalledTimes(1)
                expect(dashCalls(ctx)).toEqual([[10, 10], []])
            })
        })

        it('rounds non-integer indices', () => {
            const ctx = mockCanvasContext()
            const series = makeSeries({
                key: 's1',
                data: [10, 20, 30, 40, 50],
                dashedFromIndex: 3.6,
            })
            drawLine(makeDrawContext(ctx, ['a', 'b', 'c', 'd', 'e']), series)
            // Rounded to 4: solid [0..3], dashed [3..4].
            expect(ctx.beginPath).toHaveBeenCalledTimes(2)
        })

        it('honors series.dashedPattern override', () => {
            const ctx = mockCanvasContext()
            const series = makeSeries({
                key: 's1',
                data: [10, 20, 30, 40],
                dashedFromIndex: 2,
                dashedPattern: [2, 8],
            })
            drawLine(makeDrawContext(ctx, ['a', 'b', 'c', 'd']), series)
            expect(dashCalls(ctx)).toEqual([[], [2, 8], []])
        })

        it('uses series.dashPattern for the non-dashed subpath', () => {
            const ctx = mockCanvasContext()
            const series = makeSeries({
                key: 's1',
                data: [10, 20, 30, 40],
                dashPattern: [2, 2],
                dashedFromIndex: 2,
            })
            drawLine(makeDrawContext(ctx, ['a', 'b', 'c', 'd']), series)
            expect(dashCalls(ctx)).toEqual([[2, 2], [10, 10], []])
        })

        it('applies partial dashing against the yValues override length, not series.data', () => {
            const ctx = mockCanvasContext()
            const series = makeSeries({
                key: 's1',
                data: [0, 0, 0, 0], // longer than yValues override
                dashedFromIndex: 1,
            })
            drawLine(makeDrawContext(ctx, ['a', 'b']), series, [10, 90])
            // yValues is length 2, dashedFromIndex = 1: solid [0..0] (empty, skipped), dashed [0..1].
            expect(ctx.beginPath).toHaveBeenCalledTimes(1)
            expect(dashCalls(ctx)).toEqual([[10, 10], []])
        })

        it('does not crash on a length-1 data array', () => {
            const ctx = mockCanvasContext()
            const series = makeSeries({ key: 's1', data: [42], dashedFromIndex: 0 })
            drawLine(makeDrawContext(ctx, ['a']), series)
            // Whole line dashed, but with only one point there are no segments to draw.
            expect(ctx.beginPath).toHaveBeenCalledTimes(1)
            expect(ctx.moveTo).toHaveBeenCalledTimes(1)
            expect(ctx.lineTo).toHaveBeenCalledTimes(0)
        })
    })

    describe('drawArea — stacked bands', () => {
        it('traces bottom values in reverse when bottomValues is provided', () => {
            const ctx = mockCanvasContext()
            const labels = ['a', 'b', 'c']
            const series = makeSeries({ key: 's1', data: [0, 0, 0] })
            const drawCtx = makeDrawContext(ctx, labels)
            const yValues = [80, 90, 70]
            const bottomValues = [20, 30, 10]

            drawArea(drawCtx, series, yValues, bottomValues)

            expect(ctx.fill).toHaveBeenCalledTimes(1)
            // Top edge: moveTo(a, 80) → lineTo(b, 90) → lineTo(c, 70)
            // Bottom edge in reverse: lineTo(c, 10) → lineTo(b, 30) → lineTo(a, 20)
            const lineToArgs = ctx.lineTo.mock.calls.map(([, y]: [number, number]) => y)
            const moveToArgs = ctx.moveTo.mock.calls.map(([, y]: [number, number]) => y)

            const yScale = drawCtx.yScale
            // First point is moveTo (top of first point)
            expect(moveToArgs[0]).toBe(yScale(80))
            // lineTo calls: top[1], top[2], bottom[2], bottom[1], bottom[0]
            expect(lineToArgs[0]).toBe(yScale(90))
            expect(lineToArgs[1]).toBe(yScale(70))
            expect(lineToArgs[2]).toBe(yScale(10))
            expect(lineToArgs[3]).toBe(yScale(30))
            expect(lineToArgs[4]).toBe(yScale(20))
        })

        it('falls back to baseline when bottomValues is not provided', () => {
            const ctx = mockCanvasContext()
            const labels = ['a', 'b']
            const series = makeSeries({ key: 's1', data: [50, 80] })
            const drawCtx = makeDrawContext(ctx, labels)
            const baseline = dimensions.plotTop + dimensions.plotHeight

            drawArea(drawCtx, series)

            const lineToArgs = ctx.lineTo.mock.calls.map(([, y]: [number, number]) => y)
            // Last two lineTo calls should be at the baseline
            expect(lineToArgs[lineToArgs.length - 1]).toBe(baseline)
            expect(lineToArgs[lineToArgs.length - 2]).toBe(baseline)
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
