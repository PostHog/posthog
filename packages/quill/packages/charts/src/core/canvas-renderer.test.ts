import { type ScaleLinear, scaleLinear, scalePoint } from 'd3-scale'

import { dimensions, makeSeries } from '../testing'
import {
    composeDrawHoverWithCrosshair,
    composeDrawHoverWithSelection,
    type DrawContext,
    drawArea,
    drawGrid,
    drawLine,
    drawLineSeriesLayer,
    drawSelectionRect,
} from './canvas-renderer'
import type { ChartDrawArgs, ChartTheme } from './types'

function mockCanvasContext(): jest.Mocked<CanvasRenderingContext2D> {
    return {
        beginPath: jest.fn(),
        moveTo: jest.fn(),
        lineTo: jest.fn(),
        stroke: jest.fn(),
        fill: jest.fn(),
        closePath: jest.fn(),
        bezierCurveTo: jest.fn(),
        arc: jest.fn(),
        fillRect: jest.fn(),
        strokeRect: jest.fn(),
        rect: jest.fn(),
        save: jest.fn(),
        clip: jest.fn(),
        restore: jest.fn(),
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
    const xScale = scalePoint<string>().domain(labels).range([48, 784]).padding(0)
    const yScale = scaleLinear().domain([0, 100]).range([368, 16])
    return { ctx, dimensions, xScale, yScale, labels }
}

/** Builds a DrawContext where specific y-values produce Infinity (simulating gaps). */
function makeDrawContextWithGaps(ctx: CanvasRenderingContext2D, labels: string[], gapValues: Set<number>): DrawContext {
    const xScale = scalePoint<string>().domain(labels).range([48, 784])
    const origYScale = scaleLinear().domain([0, 100]).range([368, 16])
    const patchedYScale = (v: number): number => (gapValues.has(v) ? Infinity : origYScale(v))
    Object.assign(patchedYScale, origYScale)
    return { ctx, dimensions, xScale, yScale: patchedYScale as any, labels }
}

/** Collects the dash-pattern argument of every setLineDash call, including the trailing [] reset. */
function dashCalls(ctx: jest.Mocked<CanvasRenderingContext2D>): number[][] {
    return ctx.setLineDash.mock.calls.map(([p]) => p as number[])
}

function makeDrawArgs(ctx: CanvasRenderingContext2D, overrides: Partial<ChartDrawArgs> = {}): ChartDrawArgs {
    return {
        ctx,
        dimensions,
        scales: { x: () => undefined, y: () => 0, yTicks: () => [] },
        series: [],
        labels: ['Mon', 'Tue', 'Wed'],
        hoverIndex: -1,
        hoverPosition: null,
        theme: {} as ChartTheme,
        hoverProgress: 1,
        resetHoverFade: () => 0,
        ...overrides,
    }
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

    describe('drawLine — monotone smoothing and yFloor', () => {
        it('emits one bezier segment per point pair and no interior lineTo when smooth', () => {
            const ctx = mockCanvasContext()
            const labels = ['a', 'b', 'c', 'd']
            const series = makeSeries({ key: 's1', data: [10, 90, 30, 60] })
            drawLine({ ...makeDrawContext(ctx, labels), smooth: true }, series)
            expect(ctx.moveTo).toHaveBeenCalledTimes(1)
            expect(ctx.bezierCurveTo).toHaveBeenCalledTimes(3)
            expect(ctx.lineTo).not.toHaveBeenCalled()
        })

        it('keeps every bezier control point within the data extremes (no overshoot past a peak)', () => {
            const ctx = mockCanvasContext()
            const labels = ['a', 'b', 'c']
            const series = makeSeries({ key: 's1', data: [10, 90, 10] })
            const drawCtx = { ...makeDrawContext(ctx, labels), smooth: true }
            drawLine(drawCtx, series)
            const pointYs = [10, 90, 10].map((v) => drawCtx.yScale(v))
            const [minY, maxY] = [Math.min(...pointYs), Math.max(...pointYs)]
            const cpYs = ctx.bezierCurveTo.mock.calls.flatMap(([, cp1y, , cp2y, , endY]) => [cp1y, cp2y, endY])
            expect(Math.min(...cpYs)).toBeGreaterThanOrEqual(minY)
            expect(Math.max(...cpYs)).toBeLessThanOrEqual(maxY)
        })

        it('splits the smooth curve into separate subpaths at gaps', () => {
            const ctx = mockCanvasContext()
            const labels = ['a', 'b', 'c', 'd', 'e']
            const series = makeSeries({ key: 's1', data: [10, 20, 50, 70, 90] })
            drawLine({ ...makeDrawContextWithGaps(ctx, labels, new Set([50])), smooth: true }, series)
            expect(ctx.moveTo).toHaveBeenCalledTimes(2)
            expect(ctx.bezierCurveTo).toHaveBeenCalledTimes(2)
        })

        it.each([{ smooth: false }, { smooth: true }])(
            'clamps drawn y coordinates to yFloor (smooth: $smooth)',
            ({ smooth }) => {
                const ctx = mockCanvasContext()
                const labels = ['a', 'b', 'c']
                const series = makeSeries({ key: 's1', data: [0, 80, 0] })
                const drawCtx = makeDrawContext(ctx, labels)
                const yFloor = drawCtx.yScale(0) - 1
                drawLine({ ...drawCtx, smooth, yFloor }, series)
                const drawnYs = [
                    ...ctx.moveTo.mock.calls.map(([, y]) => y),
                    ...ctx.lineTo.mock.calls.map(([, y]) => y),
                    ...ctx.bezierCurveTo.mock.calls.flatMap(([, cp1y, , cp2y, , endY]) => [cp1y, cp2y, endY]),
                ]
                expect(drawnYs.length).toBeGreaterThan(0)
                expect(Math.max(...drawnYs)).toBeLessThanOrEqual(yFloor)
            }
        )

        it('smooths both area edges with bezier segments so stacked bottoms match the curve below', () => {
            const ctx = mockCanvasContext()
            const labels = ['a', 'b', 'c']
            const series = makeSeries({ key: 's1', data: [10, 90, 30], fill: { opacity: 0.5 } })
            drawArea({ ...makeDrawContext(ctx, labels), smooth: true }, series)
            expect(ctx.bezierCurveTo).toHaveBeenCalledTimes(4)
            expect(ctx.fill).toHaveBeenCalled()
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

    describe('drawLine — fractional tail dash (stroke.partial.fromFraction)', () => {
        it.each([
            // A two-point line: solid first half, dashed second half. One subpath each.
            { name: 'two points, 0.5 → solid half + dashed half', data: [10, 90], labels: ['a', 'b'], fraction: 0.5 },
            // Leading points stay solid; only the final segment's tail dashes.
            {
                name: 'three points, 0.5 → leading solid, final-segment tail dashed',
                data: [10, 20, 30],
                labels: ['a', 'b', 'c'],
                fraction: 0.5,
            },
        ])('$name: two subpaths, solid then dashed', ({ data, labels, fraction }) => {
            const ctx = mockCanvasContext()
            const series = makeSeries({ key: 's1', data, stroke: { partial: { fromFraction: fraction } } })
            drawLine(makeDrawContext(ctx, labels), series)
            expect(ctx.beginPath).toHaveBeenCalledTimes(2)
            expect(dashCalls(ctx)).toEqual([[], [10, 10], []])
        })

        it('dashes the tail with the partial pattern override', () => {
            const ctx = mockCanvasContext()
            const series = makeSeries({
                key: 's1',
                data: [10, 90],
                stroke: { partial: { fromFraction: 0.5, pattern: [2, 8] } },
            })
            drawLine(makeDrawContext(ctx, ['a', 'b']), series)
            expect(dashCalls(ctx)).toEqual([[], [2, 8], []])
        })

        it('takes precedence over fromIndex', () => {
            const ctx = mockCanvasContext()
            const series = makeSeries({
                key: 's1',
                data: [10, 90],
                stroke: { partial: { fromFraction: 0.5, fromIndex: 0 } },
            })
            drawLine(makeDrawContext(ctx, ['a', 'b']), series)
            // fromIndex 0 alone would be a single whole-line dashed stroke; the fraction path splits it.
            expect(ctx.beginPath).toHaveBeenCalledTimes(2)
            expect(dashCalls(ctx)).toEqual([[], [10, 10], []])
        })

        it.each([
            { name: 'two points', data: [10, 90], labels: ['a', 'b'] },
            { name: 'three points (leading segment stays curved)', data: [10, 40, 90], labels: ['a', 'b', 'c'] },
        ])('$name, smooth → tail follows the curve as a bezier, never a straight chord', ({ data, labels }) => {
            const ctx = mockCanvasContext()
            const series = makeSeries({ key: 's1', data, stroke: { partial: { fromFraction: 0.5 } } })
            drawLine({ ...makeDrawContext(ctx, labels), smooth: true }, series)
            // The straight-line branch would emit lineTo for the split bridge and the tail; the smooth
            // split draws both the solid body and the dashed tail as bezier segments instead.
            expect(ctx.lineTo).not.toHaveBeenCalled()
            expect(ctx.bezierCurveTo).toHaveBeenCalled()
            expect(ctx.beginPath).toHaveBeenCalledTimes(2)
            expect(dashCalls(ctx)).toEqual([[], [10, 10], []])
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

    describe('drawArea — gradient fill', () => {
        it('uses a vertical CanvasGradient as fillStyle when fill.gradient is true', () => {
            const ctx = mockCanvasContext()
            const gradient = { addColorStop: jest.fn() } as unknown as CanvasGradient
            ;(ctx as unknown as { createLinearGradient: jest.Mock }).createLinearGradient = jest
                .fn()
                .mockReturnValue(gradient)

            const labels = ['a', 'b', 'c']
            const series = makeSeries({ key: 's', data: [10, 20, 30], color: '#22d3ee', fill: { gradient: true } })

            const recordedFillStyles: unknown[] = []
            Object.defineProperty(ctx, 'fillStyle', {
                get: () => undefined,
                set: (v) => recordedFillStyles.push(v),
            })

            drawArea(makeDrawContext(ctx, labels), series)

            expect(ctx.createLinearGradient).toHaveBeenCalledWith(
                0,
                dimensions.plotTop,
                0,
                dimensions.plotTop + dimensions.plotHeight
            )
            expect(gradient.addColorStop).toHaveBeenCalledWith(0, '#22d3ee')
            expect(gradient.addColorStop).toHaveBeenCalledWith(1, 'transparent')
            expect(recordedFillStyles).toContain(gradient)
        })

        it('ignores gradient when lowerData is set (fill-between needs a solid fill)', () => {
            const ctx = mockCanvasContext()
            ;(ctx as unknown as { createLinearGradient: jest.Mock }).createLinearGradient = jest.fn()
            const labels = ['a', 'b']
            const series = makeSeries({ key: 's', data: [50, 80], color: '#22d3ee', fill: { gradient: true } })
            drawArea(makeDrawContext(ctx, labels), series, undefined, [10, 20])
            expect(ctx.createLinearGradient).not.toHaveBeenCalled()
        })

        it('lets the area extend below baseline when bottomValues is omitted (single-series negative case)', () => {
            // LineChart now skips stacking for a single fillable series, so drawArea is called
            // without bottomValues — meaning negative data is plotted against the raw scale,
            // not clamped to the baseline by a stacked band's Math.max(0, raw).
            const ctx = mockCanvasContext()
            const labels = ['a', 'b', 'c']
            const series = makeSeries({ key: 's', data: [10, -5, 20], color: '#22d3ee', fill: {} })
            drawArea(makeDrawContext(ctx, labels), series)
            const baseline = dimensions.plotTop + dimensions.plotHeight
            const lineToYs = (ctx.lineTo as jest.Mock).mock.calls.map(([, y]) => y as number)
            expect(lineToYs.some((y) => y > baseline)).toBe(true)
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

        // The shaded (solid) area must end exactly where the trailing dashed/hatched area begins — same
        // boundary the stroke uses — so the fill doesn't bleed a segment past where the line turns dashed.
        it('solid fill meets the trailing hatch at one shared boundary, no overlap or gap', () => {
            const fillRanges: { min: number; max: number }[] = []
            let xs: number[] = []
            const ctx = Object.assign(mockCanvasContext(), {
                beginPath: jest.fn(() => {
                    xs = []
                }),
                moveTo: jest.fn((x: number) => {
                    xs.push(x)
                }),
                lineTo: jest.fn((x: number) => {
                    xs.push(x)
                }),
                fill: jest.fn(() => {
                    fillRanges.push({ min: Math.min(...xs), max: Math.max(...xs) })
                }),
            }) as unknown as jest.Mocked<CanvasRenderingContext2D>

            const labels = ['a', 'b', 'c', 'd', 'e']
            const series = makeSeries({ key: 's', data: [10, 20, 30, 40, 50], stroke: { partial: { fromIndex: 3 } } })
            drawArea(makeDrawContext(ctx, labels), series)

            // Call order is solid then trailing hatch.
            expect(fillRanges).toHaveLength(2)
            const [solid, hatch] = fillRanges
            expect(solid.max).toBe(hatch.min)
        })

        // A gradient fill must survive partial dashing — only the stroke dashes, so the fill stays a
        // single gradient area rather than flipping to the solid + hatch treatment.
        it('keeps a single gradient fill (no hatch) when the line is partially dashed', () => {
            const ctx = mockCanvasContext()
            const gradient = { addColorStop: jest.fn() } as unknown as CanvasGradient
            ;(ctx as unknown as { createLinearGradient: jest.Mock }).createLinearGradient = jest
                .fn()
                .mockReturnValue(gradient)
            const recordedFillStyles: unknown[] = []
            Object.defineProperty(ctx, 'fillStyle', {
                get: () => undefined,
                set: (v) => recordedFillStyles.push(v),
            })

            const series = makeSeries({
                key: 's',
                data: [10, 20, 30, 40, 50],
                fill: { gradient: true },
                stroke: { partial: { fromIndex: 3 } },
            })
            drawArea(makeDrawContext(ctx, ['a', 'b', 'c', 'd', 'e']), series)

            expect(ctx.fill).toHaveBeenCalledTimes(1)
            expect(recordedFillStyles).toEqual([gradient])
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
        it('draws a horizontal line at the first y-tick (vertical orientation)', () => {
            const ctx = mockCanvasContext()
            drawGrid(makeDrawContext(ctx, ['a', 'b']))
            // Implementation emits the same shape for every tick, so one representative is enough.
            const [fromX, fromY] = ctx.moveTo.mock.calls[0]
            const [toX, toY] = ctx.lineTo.mock.calls[0]
            expect(fromX).toBe(dimensions.plotLeft)
            expect(toX).toBe(dimensions.plotLeft + dimensions.plotWidth)
            expect(fromY).toBe(toY)
        })

        it('frames the plot area with left and right vertical axis lines', () => {
            const ctx = mockCanvasContext()
            drawGrid(makeDrawContext(ctx, ['a', 'b']))
            const leftX = dimensions.plotLeft + 0.5
            const rightX = dimensions.plotLeft + dimensions.plotWidth - 0.5
            expect(ctx.moveTo.mock.calls).toContainEqual([leftX, dimensions.plotTop])
            expect(ctx.lineTo.mock.calls).toContainEqual([leftX, dimensions.plotTop + dimensions.plotHeight])
            expect(ctx.moveTo.mock.calls).toContainEqual([rightX, dimensions.plotTop])
            expect(ctx.lineTo.mock.calls).toContainEqual([rightX, dimensions.plotTop + dimensions.plotHeight])
        })

        it('uses the provided gridColor', () => {
            const ctx = mockCanvasContext()
            drawGrid(makeDrawContext(ctx, ['a', 'b']), { gridColor: 'rgb(1, 2, 3)' })
            expect(ctx.strokeStyle).toBe('rgb(1, 2, 3)')
        })

        it('draws a vertical line at the first value-tick (horizontal orientation)', () => {
            const ctx = mockCanvasContext()
            drawGrid(makeDrawContext(ctx, ['a', 'b']), { orientation: 'horizontal' })
            const [fromX, fromY] = ctx.moveTo.mock.calls[0]
            const [toX, toY] = ctx.lineTo.mock.calls[0]
            expect(fromX).toBe(toX)
            expect(fromY).toBe(dimensions.plotTop)
            expect(toY).toBe(dimensions.plotTop + dimensions.plotHeight)
        })

        it('frames the plot area with top and bottom baselines (horizontal orientation)', () => {
            const ctx = mockCanvasContext()
            drawGrid(makeDrawContext(ctx, ['a', 'b']), { orientation: 'horizontal' })
            const topY = dimensions.plotTop + 0.5
            const bottomY = dimensions.plotTop + dimensions.plotHeight - 0.5
            expect(ctx.moveTo.mock.calls).toContainEqual([dimensions.plotLeft, topY])
            expect(ctx.lineTo.mock.calls).toContainEqual([dimensions.plotLeft + dimensions.plotWidth, topY])
            expect(ctx.moveTo.mock.calls).toContainEqual([dimensions.plotLeft, bottomY])
            expect(ctx.lineTo.mock.calls).toContainEqual([dimensions.plotLeft + dimensions.plotWidth, bottomY])
        })

        describe('categoryTicks', () => {
            // Coords snap to integer + 0.5 for crisp 1px strokes (e.g. 123 → 123.5).
            it.each([
                {
                    orientation: 'vertical' as const,
                    tick: 123,
                    expectedMove: [123.5, dimensions.plotTop],
                    expectedLine: [123.5, dimensions.plotTop + dimensions.plotHeight],
                },
                {
                    orientation: 'horizontal' as const,
                    tick: 200,
                    expectedMove: [dimensions.plotLeft, 200.5],
                    expectedLine: [dimensions.plotLeft + dimensions.plotWidth, 200.5],
                },
            ])(
                '$orientation categoryTicks span the full cross axis at the snapped coord',
                ({ orientation, tick, expectedMove, expectedLine }) => {
                    const ctx = mockCanvasContext()
                    drawGrid(makeDrawContext(ctx, ['a', 'b']), { orientation, categoryTicks: [tick] })
                    expect(ctx.moveTo.mock.calls).toContainEqual(expectedMove)
                    expect(ctx.lineTo.mock.calls).toContainEqual(expectedLine)
                }
            )

            it.each([{ orientation: 'vertical' as const }, { orientation: 'horizontal' as const }])(
                'skips non-finite categoryTicks ($orientation)',
                ({ orientation }) => {
                    const finiteOnly = mockCanvasContext()
                    drawGrid(makeDrawContext(finiteOnly, ['a', 'b']), { orientation, categoryTicks: [200] })

                    const withNonFinite = mockCanvasContext()
                    drawGrid(makeDrawContext(withNonFinite, ['a', 'b']), {
                        orientation,
                        categoryTicks: [Number.NaN, 200, Number.POSITIVE_INFINITY],
                    })

                    expect(withNonFinite.moveTo.mock.calls.length).toBe(finiteOnly.moveTo.mock.calls.length)
                }
            )
        })
    })

    describe('composeDrawHoverWithCrosshair', () => {
        function makeArgs(
            ctx: CanvasRenderingContext2D,
            hoverIndex: number,
            xValue: number | undefined
        ): ChartDrawArgs {
            return makeDrawArgs(ctx, { hoverIndex, scales: { x: () => xValue, y: () => 0, yTicks: () => [] } })
        }

        it('always invokes the underlying drawHover', () => {
            const ctx = mockCanvasContext()
            const drawHover = jest.fn()
            const composed = composeDrawHoverWithCrosshair(() => drawHover, {
                crosshairColor: '#f00',
                showCrosshair: true,
            })
            composed(makeArgs(ctx, 1, 200))
            expect(drawHover).toHaveBeenCalledTimes(1)
        })

        it('skips crosshair when showCrosshair is false', () => {
            const ctx = mockCanvasContext()
            const composed = composeDrawHoverWithCrosshair(() => jest.fn(), {
                crosshairColor: '#f00',
                showCrosshair: false,
            })
            composed(makeArgs(ctx, 1, 200))
            expect(ctx.stroke).not.toHaveBeenCalled()
        })

        it('skips crosshair when crosshairColor is undefined', () => {
            const ctx = mockCanvasContext()
            const composed = composeDrawHoverWithCrosshair(() => jest.fn(), {
                crosshairColor: undefined,
                showCrosshair: true,
            })
            composed(makeArgs(ctx, 1, 200))
            expect(ctx.stroke).not.toHaveBeenCalled()
        })

        it('skips crosshair when hoverIndex is negative', () => {
            const ctx = mockCanvasContext()
            const composed = composeDrawHoverWithCrosshair(() => jest.fn(), {
                crosshairColor: '#f00',
                showCrosshair: true,
            })
            composed(makeArgs(ctx, -1, 200))
            expect(ctx.stroke).not.toHaveBeenCalled()
        })

        it('skips crosshair when scales.x returns a non-finite value', () => {
            const ctx = mockCanvasContext()
            const composed = composeDrawHoverWithCrosshair(() => jest.fn(), {
                crosshairColor: '#f00',
                showCrosshair: true,
            })
            composed(makeArgs(ctx, 1, undefined))
            expect(ctx.stroke).not.toHaveBeenCalled()
        })

        it('draws the crosshair on the happy path', () => {
            const ctx = mockCanvasContext()
            const drawHover = jest.fn()
            const composed = composeDrawHoverWithCrosshair(() => drawHover, {
                crosshairColor: '#abc',
                showCrosshair: true,
            })
            composed(makeArgs(ctx, 1, 200))
            expect(ctx.stroke).toHaveBeenCalled()
            expect(ctx.strokeStyle).toBe('#abc')
            expect(drawHover).toHaveBeenCalledTimes(1)
        })

        it('uses labelToCoord when provided in horizontal orientation', () => {
            const ctx = mockCanvasContext()
            const drawHover = jest.fn()
            const labelToCoord = jest.fn((label: string) => (label === 'Tue' ? 150 : undefined))
            const composed = composeDrawHoverWithCrosshair(() => drawHover, {
                crosshairColor: '#0f0',
                showCrosshair: true,
                axisOrientation: 'horizontal',
                labelToCoord,
            })
            composed(makeArgs(ctx, 1, 200))
            expect(labelToCoord).toHaveBeenCalledWith('Tue')
            const moves = (ctx.moveTo as jest.Mock).mock.calls
            const lines = (ctx.lineTo as jest.Mock).mock.calls
            const lastMove = moves[moves.length - 1]
            const lastLine = lines[lines.length - 1]
            expect(lastMove[1]).toBeCloseTo(lastLine[1])
            expect(lastMove[0]).not.toBeCloseTo(lastLine[0])
        })

        it('reads the latest drawHover via the getter on each call', () => {
            const ctx = mockCanvasContext()
            const first = jest.fn()
            const second = jest.fn()
            let current = first
            const composed = composeDrawHoverWithCrosshair(() => current, {
                crosshairColor: '#f00',
                showCrosshair: false,
            })
            composed(makeArgs(ctx, 0, 100))
            current = second
            composed(makeArgs(ctx, 0, 100))
            expect(first).toHaveBeenCalledTimes(1)
            expect(second).toHaveBeenCalledTimes(1)
        })
    })

    describe('drawSelectionRect', () => {
        it('draws a fill and a stroke for a positive rect', () => {
            const ctx = mockCanvasContext()
            drawSelectionRect(ctx, { x: 100, y: 20, width: 50, height: 200 })
            expect(ctx.fillRect).toHaveBeenCalledWith(100, 20, 50, 200)
            // Stroke is inset by half a pixel so the 1px border lands on whole pixels.
            expect(ctx.strokeRect).toHaveBeenCalledWith(100.5, 20.5, 49, 199)
        })

        it('is a no-op for a zero-width rect', () => {
            const ctx = mockCanvasContext()
            drawSelectionRect(ctx, { x: 100, y: 20, width: 0, height: 200 })
            expect(ctx.fillRect).not.toHaveBeenCalled()
            expect(ctx.strokeRect).not.toHaveBeenCalled()
        })

        it('is a no-op for a zero-height rect', () => {
            const ctx = mockCanvasContext()
            drawSelectionRect(ctx, { x: 100, y: 20, width: 50, height: 0 })
            expect(ctx.fillRect).not.toHaveBeenCalled()
            expect(ctx.strokeRect).not.toHaveBeenCalled()
        })
    })

    describe('composeDrawHoverWithSelection', () => {
        const plotLeft = dimensions.plotLeft
        const plotTop = dimensions.plotTop
        const plotWidth = dimensions.plotWidth
        const plotHeight = dimensions.plotHeight

        function makeSelectionArgs(
            ctx: CanvasRenderingContext2D,
            dragRect: { x0: number; x1: number } | null
        ): ChartDrawArgs {
            return makeDrawArgs(ctx, { dragRect })
        }

        it('always invokes the underlying drawHover', () => {
            const ctx = mockCanvasContext()
            const base = jest.fn()
            composeDrawHoverWithSelection(base)(makeSelectionArgs(ctx, null))
            expect(base).toHaveBeenCalledTimes(1)
        })

        it('draws nothing when there is no active drag', () => {
            const ctx = mockCanvasContext()
            composeDrawHoverWithSelection(jest.fn())(makeSelectionArgs(ctx, null))
            expect(ctx.fillRect).not.toHaveBeenCalled()
        })

        it('draws a full-plot-height band spanning the dragged range', () => {
            const ctx = mockCanvasContext()
            composeDrawHoverWithSelection(jest.fn())(
                makeSelectionArgs(ctx, { x0: plotLeft + 100, x1: plotLeft + 250 })
            )
            expect(ctx.fillRect).toHaveBeenCalledWith(plotLeft + 100, plotTop, 150, plotHeight)
        })

        it('normalizes a right-to-left drag before drawing', () => {
            const ctx = mockCanvasContext()
            composeDrawHoverWithSelection(jest.fn())(
                makeSelectionArgs(ctx, { x0: plotLeft + 250, x1: plotLeft + 100 })
            )
            expect(ctx.fillRect).toHaveBeenCalledWith(plotLeft + 100, plotTop, 150, plotHeight)
        })

        it('clamps a drag that extends past the plot edges', () => {
            const ctx = mockCanvasContext()
            composeDrawHoverWithSelection(jest.fn())(
                makeSelectionArgs(ctx, { x0: -500, x1: plotLeft + plotWidth + 500 })
            )
            expect(ctx.fillRect).toHaveBeenCalledWith(plotLeft, plotTop, plotWidth, plotHeight)
        })

        it('draws nothing when the selection collapses to zero width', () => {
            const ctx = mockCanvasContext()
            composeDrawHoverWithSelection(jest.fn())(
                makeSelectionArgs(ctx, { x0: plotLeft + 10, x1: plotLeft + 10 })
            )
            expect(ctx.fillRect).not.toHaveBeenCalled()
        })
    })

    describe('drawLineSeriesLayer — clipLeftEdge', () => {
        const labels = ['a', 'b', 'c']
        const series = [makeSeries({ key: 's1', data: [10, 50, 90] })]
        const xScale = scalePoint<string>().domain(labels).range([48, 784]).padding(0)
        const yScale = scaleLinear().domain([0, 100]).range([368, 16])
        const resolveYScale = (): ScaleLinear<number, number> => yScale

        it.each([
            { clipLeftEdge: true, expectedLeft: Math.round(dimensions.plotLeft), expectedWidth: dimensions.width - Math.round(dimensions.plotLeft) },
            { clipLeftEdge: false, expectedLeft: 0, expectedWidth: dimensions.width },
        ])(
            'passes left=$expectedLeft width=$expectedWidth to ctx.rect when clipLeftEdge=$clipLeftEdge',
            ({ clipLeftEdge, expectedLeft, expectedWidth }) => {
                const ctx = mockCanvasContext()
                drawLineSeriesLayer({ ctx, dimensions, labels, series, xScale, resolveYScale, clipLeftEdge })
                const rectCall = ctx.rect.mock.calls[0]
                expect(rectCall[0]).toBe(expectedLeft)
                expect(rectCall[2]).toBe(expectedWidth)
            }
        )
    })
})
