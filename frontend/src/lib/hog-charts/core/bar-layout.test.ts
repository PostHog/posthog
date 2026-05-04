import { dimensions, makeSeries } from '../testing'
import { type ComputeSeriesBarsOptions, computeSeriesBars, cornersFor } from './bar-layout'
import type { BarRect } from './canvas-renderer'
import { computeStackData, createBarScales } from './scales'
import type { ChartDimensions } from './types'

// Compact plot area chosen so band/value scales produce round pixel values for snapshots.
const PIXEL_TEST_DIMENSIONS: ChartDimensions = {
    width: 200,
    height: 100,
    plotLeft: 0,
    plotTop: 0,
    plotWidth: 200,
    plotHeight: 100,
}

function layoutOf(
    args: Partial<ComputeSeriesBarsOptions> & Pick<ComputeSeriesBarsOptions, 'series' | 'scales'>
): ReturnType<typeof computeSeriesBars> {
    return computeSeriesBars({ labels: ['a'], layout: 'grouped', isHorizontal: false, isTopOfStack: false, ...args })
}

describe('hog-charts bar-layout', () => {
    describe('cornersFor', () => {
        it.each([
            { isHorizontal: false, isPositive: true, expected: { topLeft: true, topRight: true } },
            { isHorizontal: false, isPositive: false, expected: { bottomLeft: true, bottomRight: true } },
            { isHorizontal: true, isPositive: true, expected: { topRight: true, bottomRight: true } },
            { isHorizontal: true, isPositive: false, expected: { topLeft: true, bottomLeft: true } },
        ])('rounds the cap end (h=$isHorizontal, +=$isPositive)', ({ isHorizontal, isPositive, expected }) => {
            expect(cornersFor(isHorizontal, isPositive, true)).toEqual(expected)
        })

        it.each([
            { isHorizontal: false, isPositive: true },
            { isHorizontal: true, isPositive: false },
        ])('returns no rounding when shouldRoundCap is false', ({ isHorizontal, isPositive }) => {
            expect(cornersFor(isHorizontal, isPositive, false)).toEqual({})
        })
    })

    describe('computeSeriesBars — grouped', () => {
        it.each([
            { desc: 'vertical positive', data: [10], isHorizontal: false, corners: { topLeft: true, topRight: true } },
            {
                desc: 'vertical negative',
                data: [-10],
                isHorizontal: false,
                corners: { bottomLeft: true, bottomRight: true },
            },
            {
                desc: 'horizontal positive',
                data: [10],
                isHorizontal: true,
                corners: { topRight: true, bottomRight: true },
            },
            {
                desc: 'horizontal negative',
                data: [-10],
                isHorizontal: true,
                corners: { topLeft: true, bottomLeft: true },
            },
        ])('rounds caps for $desc bars', ({ data, isHorizontal, corners }) => {
            const s = makeSeries({ key: 's', data })
            const scales = createBarScales([s], ['a'], dimensions, {
                barLayout: 'grouped',
                axisOrientation: isHorizontal ? 'horizontal' : 'vertical',
            })
            const bars = layoutOf({ series: s, scales, isHorizontal })
            expect(bars[0]?.corners).toEqual(corners)
            expect(bars[0]?.width).toBeGreaterThan(0)
            expect(bars[0]?.height).toBeGreaterThan(0)
        })

        it('skips bars for excluded series in the grouped sub-band', () => {
            const visible = makeSeries({ key: 'visible', data: [10] })
            const excluded = makeSeries({ key: 'excluded', data: [10], visibility: { excluded: true } })
            const scales = createBarScales([visible, excluded], ['a'], dimensions, { barLayout: 'grouped' })
            expect(layoutOf({ series: excluded, scales })[0]).toBeNull()
        })
    })

    describe('computeSeriesBars — stacked', () => {
        it('uses the band top/bottom values for stack height', () => {
            const labels = ['a', 'b']
            const a = makeSeries({ key: 'a', data: [10, 20] })
            const b = makeSeries({ key: 'b', data: [5, 15] })
            const scales = createBarScales([a, b], labels, dimensions, { barLayout: 'stacked' })
            const stackB = computeStackData([a, b], labels).get('b')!
            const bars = layoutOf({
                series: b,
                labels,
                scales,
                layout: 'stacked',
                stackedBand: stackB,
                isTopOfStack: true,
            })
            expect(bars).toHaveLength(2)
            const expectedHeight = Math.abs(scales.value(stackB.top[0]) - scales.value(stackB.bottom[0]))
            expect(bars[0]!.height).toBeCloseTo(expectedHeight, 5)
        })

        it.each([
            { layer: 'bottom', isTopOfStack: false, expectedCorners: {} },
            { layer: 'top', isTopOfStack: true, expectedCorners: { topLeft: true, topRight: true } },
        ])('rounds only the top stack layer ($layer)', ({ isTopOfStack, expectedCorners }) => {
            const a = makeSeries({ key: 'a', data: [10] })
            const b = makeSeries({ key: 'b', data: [5] })
            const scales = createBarScales([a, b], ['a'], dimensions, { barLayout: 'stacked' })
            const stacks = computeStackData([a, b], ['a'])
            const series = isTopOfStack ? b : a
            const bars = layoutOf({
                series,
                scales,
                layout: 'stacked',
                stackedBand: stacks.get(series.key),
                isTopOfStack,
            })
            expect(bars[0]?.corners).toEqual(expectedCorners)
        })

        it('throws when stackedBand is omitted for non-grouped layouts', () => {
            const s = makeSeries({ key: 's', data: [10] })
            const scales = createBarScales([s], ['a'], dimensions, { barLayout: 'stacked' })
            expect(() => layoutOf({ series: s, scales, layout: 'stacked', isTopOfStack: true })).toThrow(
                /stackedBand is required/
            )
        })
    })

    it('returns null for null/NaN data points but preserves dataIndex order', () => {
        const labels = ['a', 'b', 'c']
        const s = makeSeries({ key: 's', data: [10, NaN, 20] })
        const scales = createBarScales([s], labels, dimensions, { barLayout: 'grouped' })
        const bars = layoutOf({ series: s, labels, scales })
        expect(bars).toHaveLength(3)
        expect(bars[0]?.dataIndex).toBe(0)
        expect(bars[1]).toBeNull()
        expect(bars[2]?.dataIndex).toBe(2)
    })

    describe('computeSeriesBars — exact pixel positions', () => {
        interface PixelCase {
            name: string
            labels: string[]
            seriesData: { key: string; data: number[] }[]
            layout: 'stacked' | 'grouped'
            isHorizontal: boolean
            expected: { key: string; isTopOfStack: boolean; bars: BarRect[] }[]
        }

        it.each<PixelCase>([
            {
                name: 'vertical stacked',
                labels: ['L1', 'L2'],
                seriesData: [
                    { key: 'a', data: [25, 50] },
                    { key: 'b', data: [25, 50] },
                ],
                layout: 'stacked',
                isHorizontal: false,
                expected: [
                    {
                        key: 'a',
                        isTopOfStack: false,
                        bars: [
                            { x: 0, y: 75, width: 100, height: 25, corners: {}, dataIndex: 0 },
                            { x: 100, y: 50, width: 100, height: 50, corners: {}, dataIndex: 1 },
                        ],
                    },
                    {
                        key: 'b',
                        isTopOfStack: true,
                        bars: [
                            {
                                x: 0,
                                y: 50,
                                width: 100,
                                height: 25,
                                corners: { topLeft: true, topRight: true },
                                dataIndex: 0,
                            },
                            {
                                x: 100,
                                y: 0,
                                width: 100,
                                height: 50,
                                corners: { topLeft: true, topRight: true },
                                dataIndex: 1,
                            },
                        ],
                    },
                ],
            },
            {
                name: 'vertical grouped',
                labels: ['L1', 'L2'],
                seriesData: [
                    { key: 'a', data: [10, 20] },
                    { key: 'b', data: [20, 10] },
                ],
                layout: 'grouped',
                isHorizontal: false,
                expected: [
                    {
                        key: 'a',
                        isTopOfStack: false,
                        bars: [
                            {
                                x: 0,
                                y: 50,
                                width: 50,
                                height: 50,
                                corners: { topLeft: true, topRight: true },
                                dataIndex: 0,
                            },
                            {
                                x: 100,
                                y: 0,
                                width: 50,
                                height: 100,
                                corners: { topLeft: true, topRight: true },
                                dataIndex: 1,
                            },
                        ],
                    },
                    {
                        key: 'b',
                        isTopOfStack: false,
                        bars: [
                            {
                                x: 50,
                                y: 0,
                                width: 50,
                                height: 100,
                                corners: { topLeft: true, topRight: true },
                                dataIndex: 0,
                            },
                            {
                                x: 150,
                                y: 50,
                                width: 50,
                                height: 50,
                                corners: { topLeft: true, topRight: true },
                                dataIndex: 1,
                            },
                        ],
                    },
                ],
            },
            {
                name: 'horizontal stacked',
                labels: ['L1'],
                seriesData: [
                    { key: 'a', data: [50] },
                    { key: 'b', data: [50] },
                ],
                layout: 'stacked',
                isHorizontal: true,
                expected: [
                    {
                        key: 'a',
                        isTopOfStack: false,
                        bars: [{ x: 0, y: 0, width: 100, height: 100, corners: {}, dataIndex: 0 }],
                    },
                    {
                        key: 'b',
                        isTopOfStack: true,
                        bars: [
                            {
                                x: 100,
                                y: 0,
                                width: 100,
                                height: 100,
                                corners: { topRight: true, bottomRight: true },
                                dataIndex: 0,
                            },
                        ],
                    },
                ],
            },
            {
                name: 'vertical grouped with positive and negative values',
                labels: ['L1', 'L2'],
                seriesData: [{ key: 'a', data: [50, -50] }],
                layout: 'grouped',
                isHorizontal: false,
                expected: [
                    {
                        key: 'a',
                        isTopOfStack: false,
                        bars: [
                            {
                                x: 0,
                                y: 0,
                                width: 100,
                                height: 50,
                                corners: { topLeft: true, topRight: true },
                                dataIndex: 0,
                            },
                            {
                                x: 100,
                                y: 50,
                                width: 100,
                                height: 50,
                                corners: { bottomLeft: true, bottomRight: true },
                                dataIndex: 1,
                            },
                        ],
                    },
                ],
            },
        ])('$name', ({ labels, seriesData, layout, isHorizontal, expected }) => {
            const series = seriesData.map((s) => makeSeries(s))
            const stacks = layout === 'stacked' ? computeStackData(series, labels) : undefined
            const stackedSeries = stacks ? series.map((s) => ({ ...s, data: stacks.get(s.key)!.top })) : undefined
            const scales = createBarScales(series, labels, PIXEL_TEST_DIMENSIONS, {
                barLayout: layout,
                axisOrientation: isHorizontal ? 'horizontal' : 'vertical',
                bandPadding: 0,
                groupPadding: 0,
                stackedSeries,
            })

            for (const { key, isTopOfStack, bars: expectedBars } of expected) {
                const seriesForKey = series.find((s) => s.key === key)!
                const bars = computeSeriesBars({
                    series: seriesForKey,
                    labels,
                    scales,
                    layout,
                    isHorizontal,
                    stackedBand: stacks?.get(key),
                    isTopOfStack,
                })
                expect(bars).toEqual(expectedBars)
            }
        })
    })
})
