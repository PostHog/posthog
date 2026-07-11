import { scaleLinear } from 'd3-scale'

import { dimensions, makeSeries } from '../testing'
import {
    type BarRect,
    drawBarHighlight,
    drawBars,
    drawBarTracks,
    type DrawContext,
    traceRoundedBarPath,
} from './canvas-renderer'
import type { BarFillStyle } from './types'

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
        save: jest.fn(),
        restore: jest.fn(),
        createPattern: jest.fn(() => ({}) as CanvasPattern),
        createLinearGradient: jest.fn(() => ({ addColorStop: jest.fn() }) as unknown as CanvasGradient),
        createRadialGradient: jest.fn(() => ({ addColorStop: jest.fn() }) as unknown as CanvasGradient),
        strokeStyle: '',
        fillStyle: '',
        lineWidth: 0,
        globalAlpha: 1,
    } as unknown as jest.Mocked<CanvasRenderingContext2D>
}

function makeDrawContext(ctx: CanvasRenderingContext2D, labels: string[]): DrawContext {
    const xScale = (label: string): number | undefined => {
        const idx = labels.indexOf(label)
        return idx < 0 ? undefined : 100 + idx * 60
    }
    const yScale = scaleLinear().domain([0, 100]).range([368, 16])
    return { ctx, dimensions, xScale, yScale, labels }
}

const BASE_BAR: BarRect = { x: 100, y: 100, width: 50, height: 80, corners: {}, dataIndex: 0 }

function bar(overrides: Partial<BarRect> & { dataIndex: number }): BarRect {
    return { ...BASE_BAR, ...overrides }
}

describe('hog-charts canvas-renderer (bars)', () => {
    describe('traceRoundedBarPath', () => {
        it.each([
            { desc: 'no corners', corners: {}, expectedCurves: 0 },
            { desc: 'two top corners', corners: { topLeft: true, topRight: true }, expectedCurves: 2 },
            {
                desc: 'all four corners',
                corners: { topLeft: true, topRight: true, bottomLeft: true, bottomRight: true },
                expectedCurves: 4,
            },
            { desc: 'only one corner', corners: { topRight: true }, expectedCurves: 1 },
        ])('emits one quadraticCurveTo per rounded corner ($desc)', ({ corners, expectedCurves }) => {
            const ctx = mockCanvasContext()
            traceRoundedBarPath(ctx, 0, 0, 100, 50, 8, corners)
            expect(ctx.quadraticCurveTo).toHaveBeenCalledTimes(expectedCurves)
        })

        it('always closes the path, even when no corners are rounded or the rectangle is degenerate', () => {
            const ctx = mockCanvasContext()
            traceRoundedBarPath(ctx, 0, 0, 100, 0, 8, { topLeft: true })
            expect(ctx.closePath).toHaveBeenCalledTimes(1)
        })

        it('clamps the radius to half the smaller dimension without throwing', () => {
            const ctx = mockCanvasContext()
            traceRoundedBarPath(ctx, 0, 0, 4, 50, 20, {
                topLeft: true,
                topRight: true,
                bottomLeft: true,
                bottomRight: true,
            })
            expect(ctx.quadraticCurveTo).toHaveBeenCalledTimes(4)
        })

        it('walks corners clockwise from top-left, with each curve anchored at the right corner', () => {
            const ctx = mockCanvasContext()
            traceRoundedBarPath(ctx, 0, 0, 100, 100, 10, {
                topLeft: true,
                topRight: true,
                bottomLeft: true,
                bottomRight: true,
            })
            expect(ctx.moveTo).toHaveBeenCalledWith(10, 0)
            expect(ctx.lineTo).toHaveBeenNthCalledWith(1, 90, 0)
            expect(ctx.quadraticCurveTo).toHaveBeenNthCalledWith(1, 100, 0, 100, 10)
            expect(ctx.lineTo).toHaveBeenNthCalledWith(2, 100, 90)
            expect(ctx.quadraticCurveTo).toHaveBeenNthCalledWith(2, 100, 100, 90, 100)
            expect(ctx.lineTo).toHaveBeenNthCalledWith(3, 10, 100)
            expect(ctx.quadraticCurveTo).toHaveBeenNthCalledWith(3, 0, 100, 0, 90)
            expect(ctx.lineTo).toHaveBeenNthCalledWith(4, 0, 10)
            expect(ctx.quadraticCurveTo).toHaveBeenNthCalledWith(4, 0, 0, 10, 0)
        })
    })

    describe('drawBars', () => {
        it('does nothing when given no bars', () => {
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a', 'b'])
            drawBars(drawCtx, makeSeries({ key: 's', data: [1, 2] }), [])
            expect(ctx.fill).not.toHaveBeenCalled()
        })

        it.each([
            { desc: 'zero width', width: 0, height: 50 },
            { desc: 'negative width', width: -5, height: 50 },
            { desc: 'zero height', width: 50, height: 0 },
            { desc: 'negative height', width: 50, height: -5 },
        ])('skips a bar with $desc', ({ width, height }) => {
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a'])
            drawBars(drawCtx, makeSeries({ key: 's', data: [1] }), [
                { x: 0, y: 0, width, height, corners: {}, dataIndex: 0 },
            ])
            expect(ctx.fill).not.toHaveBeenCalled()
        })

        it('fills each non-empty bar exactly once', () => {
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a', 'b', 'c'])
            const series = makeSeries({ key: 's', data: [1, 2, 3] })
            const bars: BarRect[] = [
                bar({ x: 0, dataIndex: 0 }),
                bar({ x: 60, dataIndex: 1 }),
                bar({ x: 120, dataIndex: 2 }),
            ]
            drawBars(drawCtx, series, bars)
            expect(ctx.fill).toHaveBeenCalledTimes(3)
        })

        it('sets the series color as fillStyle for non-dashed bars', () => {
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a'])
            const series = makeSeries({ key: 's', data: [1], color: '#abcdef' })
            drawBars(drawCtx, series, [BASE_BAR])
            expect(ctx.fillStyle).toBe('#abcdef')
        })

        describe('fillStyle', () => {
            const series = makeSeries({ key: 's', data: [1], color: '#abcdef' })

            it.each<{ style: BarFillStyle; linear: number; radial: number }>([
                { style: 'flat', linear: 0, radial: 0 },
                { style: 'gradient', linear: 1, radial: 0 },
                { style: 'gloss', linear: 0, radial: 1 },
            ])('routes fillStyle=$style to the matching gradient call', ({ style, linear, radial }) => {
                const ctx = mockCanvasContext()
                drawBars(makeDrawContext(ctx, ['a']), series, [BASE_BAR], 0, style)
                expect(ctx.createLinearGradient).toHaveBeenCalledTimes(linear)
                expect(ctx.createRadialGradient).toHaveBeenCalledTimes(radial)
            })

            it('falls back to a solid color for dashed (hatched) bars regardless of fillStyle', () => {
                const ctx = mockCanvasContext()
                const dashed = makeSeries({
                    key: 's',
                    data: [1],
                    color: '#abcdef',
                    stroke: { partial: { fromIndex: 0 } },
                })
                drawBars(makeDrawContext(ctx, ['a']), dashed, [BASE_BAR], 0, 'gloss')
                expect(ctx.createRadialGradient).not.toHaveBeenCalled()
            })
        })

        it('uses per-bar colors from bars[i].color, falling back to series.color where absent', () => {
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a', 'b', 'c'])
            const series = makeSeries({
                key: 's',
                data: [1, 2, 3],
                color: '#000000',
                bars: [{ color: '#ff0000' }, {}, { color: '#0000ff' }],
            })
            const seen: (string | CanvasPattern)[] = []
            const original = Object.getOwnPropertyDescriptor(ctx, 'fillStyle')
            Object.defineProperty(ctx, 'fillStyle', {
                set(v: string | CanvasPattern) {
                    seen.push(v)
                },
                configurable: true,
            })
            try {
                drawBars(drawCtx, series, [
                    bar({ x: 0, dataIndex: 0 }),
                    bar({ x: 60, dataIndex: 1 }),
                    bar({ dataIndex: 2 }),
                ])
            } finally {
                Object.defineProperty(ctx, 'fillStyle', original!)
            }
            expect(seen).toEqual(['#ff0000', '#000000', '#0000ff'])
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
                bar({ x: 0, dataIndex: 0 }),
                bar({ x: 60, dataIndex: 1 }),
                bar({ x: 120, dataIndex: 2 }),
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
                bar({ x: 0, dataIndex: 0 }),
                bar({ x: 60, dataIndex: 1 }),
                bar({ x: 120, dataIndex: 2 }),
            ])
            expect(ctx.fill).toHaveBeenCalledTimes(3)
        })

        it('hatches bars by their dataIndex, not their array position (filtered bars stay correct)', () => {
            // Series has 5 data points; bars 0 and 2 are absent (filtered out).
            // partial.fromIndex=3 should hatch bars with dataIndex >= 3, regardless of where they sit in the array.
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a', 'b', 'c', 'd', 'e'])
            const series = makeSeries({
                key: 's',
                data: [1, 2, 3, 4, 5],
                color: '#11223344',
                stroke: { partial: { fromIndex: 3 } },
            })
            const bars = [bar({ x: 0, dataIndex: 1 }), bar({ x: 60, dataIndex: 3 }), bar({ x: 120, dataIndex: 4 })]
            const fillStyleSeen: (string | CanvasPattern)[] = []
            const original = Object.getOwnPropertyDescriptor(ctx, 'fillStyle')
            Object.defineProperty(ctx, 'fillStyle', {
                set(v) {
                    fillStyleSeen.push(v)
                },
                get() {
                    return ''
                },
            })
            drawBars(drawCtx, series, bars)
            if (original) {
                Object.defineProperty(ctx, 'fillStyle', original)
            }
            expect(fillStyleSeen[0]).toBe('#11223344')
            expect(typeof fillStyleSeen[1]).not.toBe('string')
            expect(typeof fillStyleSeen[2]).not.toBe('string')
        })

        it('hatches individual bars flagged via bars[i].hatch, including non-contiguous indices', () => {
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a', 'b', 'c'])
            const series = makeSeries({
                key: 's',
                data: [1, 2, 3],
                color: '#55667788',
                bars: [{ hatch: true }, {}, { hatch: true }],
            })
            const fillStyleSeen: (string | CanvasPattern)[] = []
            const original = Object.getOwnPropertyDescriptor(ctx, 'fillStyle')
            Object.defineProperty(ctx, 'fillStyle', {
                set(v) {
                    fillStyleSeen.push(v)
                },
                get() {
                    return ''
                },
            })
            drawBars(drawCtx, series, [
                bar({ x: 0, dataIndex: 0 }),
                bar({ x: 60, dataIndex: 1 }),
                bar({ x: 120, dataIndex: 2 }),
            ])
            if (original) {
                Object.defineProperty(ctx, 'fillStyle', original)
            }
            expect(typeof fillStyleSeen[0]).not.toBe('string')
            expect(fillStyleSeen[1]).toBe('#55667788')
            expect(typeof fillStyleSeen[2]).not.toBe('string')
        })

        it('respects the cornerRadius option', () => {
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a'])
            const series = makeSeries({ key: 's', data: [1] })
            drawBars(drawCtx, series, [{ ...BASE_BAR, corners: { topLeft: true, topRight: true } }], 12)
            expect(ctx.quadraticCurveTo).toHaveBeenCalledTimes(2)
        })

        it('does not invoke createPattern when no partial dashing is set', () => {
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a'])
            drawBars(drawCtx, makeSeries({ key: 's', data: [1] }), [BASE_BAR])
            expect(ctx.createPattern).not.toHaveBeenCalled()
        })
    })

    describe('drawBarHighlight', () => {
        it('fills a single rectangle as a translucent overlay', () => {
            const ctx = mockCanvasContext()
            drawBarHighlight(ctx, BASE_BAR, 'rgba(0,0,0,0.2)')
            expect(ctx.fill).toHaveBeenCalledTimes(1)
            expect(ctx.stroke).not.toHaveBeenCalled()
        })

        it.each([
            { desc: 'zero width', width: 0, height: 80 },
            { desc: 'negative width', width: -5, height: 80 },
            { desc: 'zero height', width: 50, height: 0 },
            { desc: 'negative height', width: 50, height: -5 },
        ])('does nothing on a bar with $desc', ({ width, height }) => {
            const ctx = mockCanvasContext()
            drawBarHighlight(ctx, { ...BASE_BAR, width, height }, 'rgba(0,0,0,0.2)')
            expect(ctx.fill).not.toHaveBeenCalled()
        })

        it('uses the provided color as fillStyle', () => {
            const ctx = mockCanvasContext()
            drawBarHighlight(ctx, BASE_BAR, 'rgba(1,2,3,0.4)')
            expect(ctx.fillStyle).toBe('rgba(1,2,3,0.4)')
        })
    })

    describe('drawBarTracks', () => {
        const series = makeSeries({ key: 's', data: [40, 70] })

        it('paints a tinted base and hatched stripes per track', () => {
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a', 'b'])
            drawBarTracks(drawCtx, series, [bar({ dataIndex: 0 }), bar({ dataIndex: 1, x: 200 })], 6)
            // Two passes (base + hatch) per track => 2 fills × 2 tracks.
            expect(ctx.fill).toHaveBeenCalledTimes(4)
        })

        it('wraps drawing in save/restore so the track alpha does not leak', () => {
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a'])
            drawBarTracks(drawCtx, series, [bar({ dataIndex: 0 })], 6)
            expect(ctx.save).toHaveBeenCalledTimes(1)
            expect(ctx.restore).toHaveBeenCalledTimes(1)
        })

        it('skips degenerate track rects', () => {
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a'])
            drawBarTracks(drawCtx, series, [bar({ dataIndex: 0, width: 0 })], 6)
            expect(ctx.fill).not.toHaveBeenCalled()
        })

        it('does nothing when there are no tracks', () => {
            const ctx = mockCanvasContext()
            const drawCtx = makeDrawContext(ctx, ['a'])
            drawBarTracks(drawCtx, series, [], 6)
            expect(ctx.fill).not.toHaveBeenCalled()
            expect(ctx.save).not.toHaveBeenCalled()
        })
    })
})
