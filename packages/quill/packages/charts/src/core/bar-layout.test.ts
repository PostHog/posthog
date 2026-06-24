import { dimensions, makeSeries } from '../testing'
import {
    bandCenter,
    type ComputeSeriesBarsOptions,
    computeBarTrackRect,
    computeSeriesBars,
    cornersFor,
    groupedBarCenter,
} from './bar-layout'
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

        it.each([
            { isHorizontal: false, isPositive: true, expected: { bottomLeft: true, bottomRight: true } },
            { isHorizontal: false, isPositive: false, expected: { topLeft: true, topRight: true } },
            { isHorizontal: true, isPositive: true, expected: { topLeft: true, bottomLeft: true } },
            { isHorizontal: true, isPositive: false, expected: { topRight: true, bottomRight: true } },
        ])('rounds the baseline end (h=$isHorizontal, +=$isPositive)', ({ isHorizontal, isPositive, expected }) => {
            expect(cornersFor(isHorizontal, isPositive, false, true)).toEqual(expected)
        })

        it('rounds both ends as a pill when cap and baseline are both set', () => {
            expect(cornersFor(true, true, true, true)).toEqual({
                topLeft: true,
                bottomLeft: true,
                topRight: true,
                bottomRight: true,
            })
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

        it('clamps the bar baseline into the plot when a fixed valueDomain excludes 0', () => {
            // valueScale(0) extrapolates below the plot for domain [50, 100]; the baseline must be
            // clamped so the bar stops at the plot edge instead of bleeding through the bottom margin.
            const s = makeSeries({ key: 's', data: [75] })
            const scales = createBarScales([s], ['a'], dimensions, {
                barLayout: 'grouped',
                valueDomain: [50, 100],
            })
            const bar = layoutOf({ series: s, scales })[0]!
            const plotBottom = dimensions.plotTop + dimensions.plotHeight
            // bottom edge of a vertical bar is y + height; it must not exceed the plot bottom.
            expect(bar.y + bar.height).toBeLessThanOrEqual(plotBottom + 0.001)
        })
    })

    describe('computeSeriesBars — stacked', () => {
        it('uses the band top/bottom values for stack height', () => {
            // Asserts on the bottom-of-stack segment, whose baseline edge is exact (no seam overlap).
            const labels = ['a', 'b']
            const a = makeSeries({ key: 'a', data: [10, 20] })
            const b = makeSeries({ key: 'b', data: [5, 15] })
            const scales = createBarScales([a, b], labels, dimensions, { barLayout: 'stacked' })
            const stackA = computeStackData([a, b], labels).get('a')!
            const bars = layoutOf({
                series: a,
                labels,
                scales,
                layout: 'stacked',
                stackedBand: stackA,
                isTopOfStack: false,
            })
            expect(bars).toHaveLength(2)
            const expectedHeight = Math.abs(scales.value(stackA.top[0]) - scales.value(stackA.bottom[0]))
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

        it('rounds both ends per band when capRoundedAtIndex/baseRoundedAtIndex are funnel-style', () => {
            // Funnel: step 0 is 100% (no filler), step 1 splits value + filler. The value segment
            // is the bottom of every band; it is also the visible top at step 0 (filler is zero).
            const labels = ['0', '1']
            const value = makeSeries({ key: 'value', data: [100, 55] })
            const filler = makeSeries({ key: 'filler', data: [0, 45] })
            const scales = createBarScales([value, filler], labels, dimensions, {
                barLayout: 'stacked',
                axisOrientation: 'horizontal',
            })
            const stacks = computeStackData([value, filler], labels)
            // Per-band non-zero edges: value is bottom at both; top at step 0, filler is top at step 1.
            const topKeyAtIndex = ['value', 'filler']
            const bottomKeyAtIndex = ['value', 'value']
            const valueBars = computeSeriesBars({
                series: value,
                labels,
                scales,
                layout: 'stacked',
                isHorizontal: true,
                stackedBand: stacks.get('value'),
                isTopOfStack: false,
                capRoundedAtIndex: (i) => topKeyAtIndex[i] === 'value',
                baseRoundedAtIndex: (i) => bottomKeyAtIndex[i] === 'value',
            })
            const fillerBars = computeSeriesBars({
                series: filler,
                labels,
                scales,
                layout: 'stacked',
                isHorizontal: true,
                stackedBand: stacks.get('filler'),
                isTopOfStack: true,
                capRoundedAtIndex: (i) => topKeyAtIndex[i] === 'filler',
                baseRoundedAtIndex: (i) => bottomKeyAtIndex[i] === 'filler',
            })
            // Step 0: value is the only segment — rounded pill on both ends.
            expect(valueBars[0]?.corners).toEqual({
                topLeft: true,
                bottomLeft: true,
                topRight: true,
                bottomRight: true,
            })
            // Step 1: value rounds the baseline (left) only; filler rounds the cap (right) only.
            expect(valueBars[1]?.corners).toEqual({ topLeft: true, bottomLeft: true })
            expect(fillerBars[1]?.corners).toEqual({ topRight: true, bottomRight: true })
        })

        it('overlaps an interior segment 0.5px into its lower neighbour, keeping baseline and cap exact', () => {
            const labels = ['L1']
            const a = makeSeries({ key: 'a', data: [50] })
            const b = makeSeries({ key: 'b', data: [50] })
            const stacks = computeStackData([a, b], labels)
            const stackedSeries = [a, b].map((s) => ({ ...s, data: stacks.get(s.key)!.top }))
            const scales = createBarScales([a, b], labels, PIXEL_TEST_DIMENSIONS, {
                barLayout: 'stacked',
                bandPadding: 0,
                groupPadding: 0,
                stackedSeries,
            })
            const opts = { labels, scales, layout: 'stacked' as const, isHorizontal: false }
            const lower = computeSeriesBars({
                ...opts,
                series: a,
                stackedBand: stacks.get('a'),
                isTopOfStack: false,
            })[0]!
            const upper = computeSeriesBars({
                ...opts,
                series: b,
                stackedBand: stacks.get('b'),
                isTopOfStack: true,
            })[0]!
            // Bottom segment sits exactly on the baseline — no 0.5px overpaint past the axis.
            expect(lower.y + lower.height).toBeCloseTo(PIXEL_TEST_DIMENSIONS.plotHeight, 5)
            // Interior (upper) segment extends its baseline edge 0.5px past the lower segment's top.
            expect(upper.y + upper.height).toBeCloseTo(lower.y + 0.5, 5)
            // Cap (away-from-baseline) edge stays exact.
            expect(upper.y).toBeCloseTo(0, 5)
        })

        it('returns nulls when stackedBand is omitted for non-grouped layouts', () => {
            const s = makeSeries({ key: 's', data: [10] })
            const scales = createBarScales([s], ['a'], dimensions, { barLayout: 'stacked' })
            const bars = layoutOf({ series: s, scales, layout: 'stacked', isTopOfStack: true })
            expect(bars).toEqual([null])
        })

        it('rounds the cap of the topmost visible series per yAxisId (multi-axis stacked)', () => {
            const labels = ['a', 'b', 'c']
            const left1 = makeSeries({ key: 'left-1', data: [10, 20, 30], yAxisId: 'left' })
            const left2 = makeSeries({ key: 'left-2', data: [5, 15, 25], yAxisId: 'left' })
            const right1 = makeSeries({ key: 'right-1', data: [1, 2, 3], yAxisId: 'right' })
            const all = [left1, left2, right1]
            const scales = createBarScales(all, labels, dimensions, { barLayout: 'stacked' })
            const stacks = computeStackData(all, labels)

            // Mirror the per-axis top resolution that BarChart performs: last visible series per axisId wins.
            const topPerAxis = new Map<string, string>()
            for (const s of all) {
                topPerAxis.set(s.yAxisId ?? 'left', s.key)
            }

            const hasRoundedCap = (bars: ReturnType<typeof layoutOf>): boolean =>
                bars.some((b) => b !== null && (b.corners.topLeft || b.corners.topRight))

            const barsFor = (s: typeof left1): ReturnType<typeof layoutOf> =>
                layoutOf({
                    series: s,
                    labels,
                    scales,
                    layout: 'stacked',
                    stackedBand: stacks.get(s.key),
                    isTopOfStack: topPerAxis.get(s.yAxisId ?? 'left') === s.key,
                })

            expect(hasRoundedCap(barsFor(left2))).toBe(true)
            expect(hasRoundedCap(barsFor(right1))).toBe(true)
            expect(hasRoundedCap(barsFor(left1))).toBe(false)
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
                        // Interior segment: baseline edge extended 0.5px into the lower neighbour.
                        bars: [
                            {
                                x: 0,
                                y: 50,
                                width: 100,
                                height: 25.5,
                                corners: { topLeft: true, topRight: true },
                                dataIndex: 0,
                            },
                            {
                                x: 100,
                                y: 0,
                                width: 100,
                                height: 50.5,
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
                        // Interior segment: baseline edge extended 0.5px into the lower neighbour.
                        bars: [
                            {
                                x: 99.5,
                                y: 0,
                                width: 100.5,
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

    describe('computeBarTrackRect', () => {
        const verticalBar: BarRect = {
            x: 100,
            y: 120,
            width: 50,
            height: 200,
            corners: { topLeft: true },
            dataIndex: 2,
        }
        const horizontalBar: BarRect = { x: 60, y: 100, width: 140, height: 40, corners: {}, dataIndex: 0 }

        it('stretches a vertical bar across the full value axis, keeping its band slot', () => {
            expect(computeBarTrackRect(verticalBar, 368, 16, false)).toEqual({
                x: 100,
                y: 16,
                width: 50,
                height: 352,
                corners: { topLeft: true },
                dataIndex: 2,
            })
        })

        it('stretches a horizontal bar across the full value axis, keeping its band slot', () => {
            expect(computeBarTrackRect(horizontalBar, 60, 540, true)).toEqual({
                x: 60,
                y: 100,
                width: 480,
                height: 40,
                corners: {},
                dataIndex: 0,
            })
        })
    })

    describe('bandCenter', () => {
        it.each([
            { label: 'a', expected: 50 },
            { label: 'b', expected: 150 },
        ])('returns the pixel center $expected for label $label', ({ label, expected }) => {
            const s = makeSeries({ key: 's', data: [10, 20] })
            const scales = createBarScales([s], ['a', 'b'], PIXEL_TEST_DIMENSIONS, {
                barLayout: 'grouped',
                bandPadding: 0,
                groupPadding: 0,
            })
            // Two bands across 200px → band width 100, centers at 50 and 150.
            expect(bandCenter(scales, label)).toBeCloseTo(expected, 5)
        })

        it('returns undefined for an unknown band', () => {
            const s = makeSeries({ key: 's', data: [10] })
            const scales = createBarScales([s], ['a'], PIXEL_TEST_DIMENSIONS, { barLayout: 'grouped' })
            expect(bandCenter(scales, 'missing')).toBeUndefined()
        })
    })

    describe('groupedBarCenter', () => {
        it.each([
            { seriesKey: 'a', expected: 25 },
            { seriesKey: 'b', expected: 75 },
        ])(
            "returns the center $expected for series $seriesKey's sub-band in a grouped layout",
            ({ seriesKey, expected }) => {
                const a = makeSeries({ key: 'a', data: [10, 20] })
                const b = makeSeries({ key: 'b', data: [20, 10] })
                const scales = createBarScales([a, b], ['L1', 'L2'], PIXEL_TEST_DIMENSIONS, {
                    barLayout: 'grouped',
                    bandPadding: 0,
                    groupPadding: 0,
                })
                // a@L1 slot x:0 w:50 → center 25; b@L1 slot x:50 w:50 → center 75 (see grouped pixel case).
                expect(groupedBarCenter(scales, 'L1', seriesKey)).toBeCloseTo(expected, 5)
            }
        )

        it('returns undefined when the series is not in the group scale', () => {
            const a = makeSeries({ key: 'a', data: [10] })
            const scales = createBarScales([a], ['L1'], PIXEL_TEST_DIMENSIONS, {
                barLayout: 'grouped',
                bandPadding: 0,
                groupPadding: 0,
            })
            expect(groupedBarCenter(scales, 'L1', 'missing')).toBeUndefined()
        })
    })
})
