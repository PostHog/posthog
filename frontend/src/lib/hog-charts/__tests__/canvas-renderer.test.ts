import * as d3 from 'd3'

import { drawArea, drawGrid, drawLine, type DrawContext } from '../core/canvas-renderer'
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
        createPattern: jest.fn(() => ({}) as CanvasPattern),
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

/** Collects the dash-pattern argument of every setLineDash call, including the trailing [] reset. */
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
                name: 'breaks the path on a non-finite y so the gap is not bridged',
                labels: ['a', 'b', 'c'],
                data: [10, 50, 90],
                gapValues: new Set([50]),
                expectedBeginPath: 1,
                expectedMoveTo: 2,
                expectedLineTo: 0,
            },
            {
                name: 'rejoins after the gap with a fresh subpath when there are valid points on both sides',
                labels: ['a', 'b', 'c', 'd', 'e'],
                data: [10, 20, 50, 70, 90],
                gapValues: new Set([50]),
                expectedBeginPath: 1,
                expectedMoveTo: 2,
                expectedLineTo: 2,
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

    describe('drawLine — partial dashing (stroke.partial)', () => {
        it.each([
            // Fast path — neither index set
            {
                name: 'neither index set → single solid stroke',
                length: 3,
                expectedBeginPath: 1,
                expectedDashCalls: [[], []],
            },
            {
                name: 'neither index set, with stroke.pattern → whole line uses pattern',
                length: 3,
                strokePattern: [4, 4],
                expectedBeginPath: 1,
                expectedDashCalls: [[4, 4], []],
            },

            // partial.fromIndex
            {
                name: 'partial.fromIndex mid-series → solid + dashed',
                length: 5,
                fromIndex: 3,
                expectedBeginPath: 2,
                expectedDashCalls: [[], [10, 10], []],
            },
            {
                name: 'partial.fromIndex === length-1 (projection tail)',
                length: 5,
                fromIndex: 4,
                expectedBeginPath: 2,
                expectedDashCalls: [[], [10, 10], []],
            },
            {
                name: 'partial.fromIndex === 0 → whole line dashed',
                length: 3,
                fromIndex: 0,
                expectedBeginPath: 1,
                expectedDashCalls: [[10, 10], []],
            },
            {
                name: 'partial.fromIndex >= length → clamped to last index (solid + trailing dashed)',
                length: 3,
                fromIndex: 99,
                expectedBeginPath: 2,
                expectedDashCalls: [[], [10, 10], []],
            },
            {
                name: 'negative partial.fromIndex → clamped to 0 (whole line dashed)',
                length: 3,
                fromIndex: -5,
                expectedBeginPath: 1,
                expectedDashCalls: [[10, 10], []],
            },

            // partial.toIndex
            {
                name: 'partial.toIndex mid-series → dashed + solid',
                length: 5,
                toIndex: 1,
                expectedBeginPath: 2,
                expectedDashCalls: [[10, 10], [], []],
            },
            {
                name: 'partial.toIndex === length-1 → whole line dashed',
                length: 3,
                toIndex: 2,
                expectedBeginPath: 1,
                expectedDashCalls: [[10, 10], []],
            },
            {
                name: 'partial.toIndex < 0 → clamped to 0 (single-index leading dash + solid rest)',
                length: 3,
                toIndex: -5,
                expectedBeginPath: 2,
                expectedDashCalls: [[10, 10], [], []],
            },
            {
                name: 'partial.toIndex beyond length → clamped to last index (whole line dashed)',
                length: 3,
                toIndex: 99,
                expectedBeginPath: 1,
                expectedDashCalls: [[10, 10], []],
            },

            // Both ends
            {
                name: 'both ends with a solid middle → dashed + solid + dashed',
                length: 7,
                toIndex: 1,
                fromIndex: 5,
                expectedBeginPath: 3,
                expectedDashCalls: [[10, 10], [], [10, 10], []],
            },
            {
                name: 'both ends meet (to === from - 1) → whole line dashed',
                length: 5,
                toIndex: 2,
                fromIndex: 3,
                expectedBeginPath: 1,
                expectedDashCalls: [[10, 10], []],
            },
            {
                name: 'both ends overlap (to > from - 1) → whole line dashed',
                length: 5,
                toIndex: 3,
                fromIndex: 2,
                expectedBeginPath: 1,
                expectedDashCalls: [[10, 10], []],
            },

            // Rounding and pattern overrides
            {
                name: 'non-integer indices rounded (3.6 → 4)',
                length: 5,
                fromIndex: 3.6,
                expectedBeginPath: 2,
                expectedDashCalls: [[], [10, 10], []],
            },
            {
                name: 'partial.pattern override applies to the dashed portion',
                length: 4,
                fromIndex: 2,
                partialPattern: [2, 8],
                expectedBeginPath: 2,
                expectedDashCalls: [[], [2, 8], []],
            },
            {
                name: 'stroke.pattern applies to the solid portion alongside partial.pattern on the dashed portion',
                length: 4,
                fromIndex: 2,
                strokePattern: [2, 2],
                expectedBeginPath: 2,
                expectedDashCalls: [[2, 2], [10, 10], []],
            },
        ])(
            '$name',
            ({ length, fromIndex, toIndex, strokePattern, partialPattern, expectedBeginPath, expectedDashCalls }) => {
                const ctx = mockCanvasContext()
                const labels = Array.from({ length }, (_, i) => String.fromCharCode(97 + i))
                const data = Array.from({ length }, (_, i) => (i + 1) * 10)
                const series = makeSeries({
                    key: 's1',
                    data,
                    stroke: {
                        pattern: strokePattern,
                        partial:
                            fromIndex !== undefined || toIndex !== undefined || partialPattern !== undefined
                                ? { fromIndex, toIndex, pattern: partialPattern }
                                : undefined,
                    },
                })
                drawLine(makeDrawContext(ctx, labels), series)
                expect(ctx.beginPath).toHaveBeenCalledTimes(expectedBeginPath)
                expect(dashCalls(ctx)).toEqual(expectedDashCalls)
            }
        )

        // Kept out of the parameterized table — asserts boundary-point sharing via moveTo/lineTo counts.
        it('shares the boundary point across adjacent subpaths', () => {
            const ctx = mockCanvasContext()
            const series = makeSeries({
                key: 's1',
                data: [10, 20, 30, 40, 50],
                stroke: { partial: { fromIndex: 3 } },
            })
            drawLine(makeDrawContext(ctx, ['a', 'b', 'c', 'd', 'e']), series)
            // Solid [0..2]: moveTo + 2 lineTos. Dashed [2..4]: moveTo + 2 lineTos.
            expect(ctx.moveTo).toHaveBeenCalledTimes(2)
            expect(ctx.lineTo).toHaveBeenCalledTimes(4)
        })

        it('applies partial dashing against the yValues override length, not series.data', () => {
            const ctx = mockCanvasContext()
            const series = makeSeries({
                key: 's1',
                data: [0, 0, 0, 0], // longer than the yValues override
                stroke: { partial: { fromIndex: 1 } },
            })
            drawLine(makeDrawContext(ctx, ['a', 'b']), series, [10, 90])
            // yValues length 2, fromIndex 1 → zero-length solid middle skipped; one dashed subpath.
            expect(ctx.beginPath).toHaveBeenCalledTimes(1)
            expect(dashCalls(ctx)).toEqual([[10, 10], []])
        })

        it('does not crash on a length-1 data array', () => {
            const ctx = mockCanvasContext()
            const series = makeSeries({ key: 's1', data: [42], stroke: { partial: { fromIndex: 0 } } })
            drawLine(makeDrawContext(ctx, ['a']), series)
            // Single point: moveTo once, no lineTo, stroke draws nothing visible.
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

    describe('drawArea — partial dashing', () => {
        it.each([
            {
                name: 'partial.fromIndex only → solid leading + hatched trailing',
                labels: ['a', 'b', 'c', 'd', 'e'],
                data: [10, 20, 30, 40, 50],
                fromIndex: 3 as number | undefined,
                toIndex: undefined as number | undefined,
                expectedFills: 2,
            },
            {
                name: 'partial.toIndex only → hatched leading + solid trailing',
                labels: ['a', 'b', 'c', 'd', 'e'],
                data: [10, 20, 30, 40, 50],
                fromIndex: undefined as number | undefined,
                toIndex: 1 as number | undefined,
                expectedFills: 2,
            },
            {
                name: 'both indices → hatched + solid + hatched',
                labels: ['a', 'b', 'c', 'd', 'e', 'f', 'g'],
                data: [10, 20, 30, 40, 50, 60, 70],
                fromIndex: 5 as number | undefined,
                toIndex: 1 as number | undefined,
                expectedFills: 3,
            },
        ])('$name', ({ labels, data, fromIndex, toIndex, expectedFills }) => {
            const ctx = mockCanvasContext()
            const series = makeSeries({ key: 's', data, stroke: { partial: { fromIndex, toIndex } } })
            drawArea(makeDrawContext(ctx, labels), series)
            expect(ctx.fill).toHaveBeenCalledTimes(expectedFills)
        })
    })

    describe('drawArea — fill.lowerData edge cases', () => {
        it.each([
            {
                name: 'shorter than data → segment breaks instead of silently baseline-filling',
                labels: ['a', 'b', 'c', 'd'],
                data: [10, 20, 30, 40],
                bottomValues: [5, 5],
                expectedFills: 1,
            },
            {
                name: 'non-finite mid-segment → splits into two fills',
                labels: ['a', 'b', 'c', 'd', 'e'],
                data: [10, 20, 30, 40, 50],
                bottomValues: [5, 5, NaN, 5, 5],
                expectedFills: 2,
            },
        ])('$name', ({ labels, data, bottomValues, expectedFills }) => {
            const ctx = mockCanvasContext()
            const series = makeSeries({ key: 's', data })
            drawArea(makeDrawContext(ctx, labels), series, undefined, bottomValues)
            expect(ctx.fill).toHaveBeenCalledTimes(expectedFills)
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

    describe('drawGrid', () => {
        it('draws a horizontal line at every y-tick', () => {
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a', 'b'])
            drawGrid(drawCtx)
            const tickCount = ctx.moveTo.mock.calls.length - 1
            expect(tickCount).toBeGreaterThan(0)
            for (let i = 0; i < tickCount; i++) {
                const [moveX, moveY] = ctx.moveTo.mock.calls[i] as [number, number]
                const [lineX, lineY] = ctx.lineTo.mock.calls[i] as [number, number]
                expect(moveX).toBe(dimensions.plotLeft)
                expect(lineX).toBe(dimensions.plotLeft + dimensions.plotWidth)
                expect(moveY).toBe(lineY)
            }
        })

        it('draws a vertical y-axis line at plotLeft as the final stroke', () => {
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a', 'b'])
            drawGrid(drawCtx)
            const lastMoveTo = ctx.moveTo.mock.calls[ctx.moveTo.mock.calls.length - 1] as [number, number]
            const lastLineTo = ctx.lineTo.mock.calls[ctx.lineTo.mock.calls.length - 1] as [number, number]
            expect(lastMoveTo[0]).toBe(dimensions.plotLeft + 0.5)
            expect(lastMoveTo[1]).toBe(dimensions.plotTop)
            expect(lastLineTo[0]).toBe(dimensions.plotLeft + 0.5)
            expect(lastLineTo[1]).toBe(dimensions.plotTop + dimensions.plotHeight)
        })

        it('uses the provided gridColor', () => {
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a', 'b'])
            drawGrid(drawCtx, { gridColor: 'rgb(1, 2, 3)' })
            expect(ctx.strokeStyle).toBe('rgb(1, 2, 3)')
        })
    })
})
