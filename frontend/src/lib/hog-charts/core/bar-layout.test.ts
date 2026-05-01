import { dimensions, makeSeries } from '../test-helpers'
import { computeSeriesBars, cornersFor } from './bar-layout'
import { computeStackData, createBarScales } from './scales'

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
            {
                desc: 'vertical positive',
                data: [10],
                isHorizontal: false,
                expectedCorners: { topLeft: true, topRight: true },
            },
            {
                desc: 'vertical negative',
                data: [-10],
                isHorizontal: false,
                expectedCorners: { bottomLeft: true, bottomRight: true },
            },
            {
                desc: 'horizontal positive',
                data: [10],
                isHorizontal: true,
                expectedCorners: { topRight: true, bottomRight: true },
            },
            {
                desc: 'horizontal negative',
                data: [-10],
                isHorizontal: true,
                expectedCorners: { topLeft: true, bottomLeft: true },
            },
        ])('rounds caps for $desc bars', ({ data, isHorizontal, expectedCorners }) => {
            const s = makeSeries({ key: 's', data })
            const scales = createBarScales([s], ['a'], dimensions, {
                barLayout: 'grouped',
                axisOrientation: isHorizontal ? 'horizontal' : 'vertical',
            })
            const bars = computeSeriesBars({
                series: s,
                labels: ['a'],
                scales,
                layout: 'grouped',
                isHorizontal,
                isTopOfStack: false,
            })
            expect(bars[0]?.corners).toEqual(expectedCorners)
            expect(bars[0]?.width).toBeGreaterThan(0)
            expect(bars[0]?.height).toBeGreaterThan(0)
        })

        it('skips bars for excluded series in the grouped sub-band', () => {
            const visible = makeSeries({ key: 'visible', data: [10] })
            const excluded = makeSeries({ key: 'excluded', data: [10], visibility: { excluded: true } })
            const scales = createBarScales([visible, excluded], ['a'], dimensions, { barLayout: 'grouped' })
            const bars = computeSeriesBars({
                series: excluded,
                labels: ['a'],
                scales,
                layout: 'grouped',
                isHorizontal: false,
                isTopOfStack: false,
            })
            expect(bars[0]).toBeNull()
        })
    })

    describe('computeSeriesBars — stacked', () => {
        it('uses the band top/bottom values for stack height', () => {
            const labels = ['a', 'b']
            const a = makeSeries({ key: 'a', data: [10, 20] })
            const b = makeSeries({ key: 'b', data: [5, 15] })
            const scales = createBarScales([a, b], labels, dimensions, { barLayout: 'stacked' })
            const stacks = computeStackData([a, b], labels)
            const stackB = stacks.get('b')!

            const bars = computeSeriesBars({
                series: b,
                labels,
                scales,
                layout: 'stacked',
                isHorizontal: false,
                stackedBand: stackB,
                isTopOfStack: true,
            })
            expect(bars).toHaveLength(2)
            const expectedHeight = Math.abs(scales.value(stackB.top[0]) - scales.value(stackB.bottom[0]))
            expect(bars[0]!.height).toBeCloseTo(expectedHeight, 5)
        })

        it('only rounds the top stack layer', () => {
            const a = makeSeries({ key: 'a', data: [10] })
            const b = makeSeries({ key: 'b', data: [5] })
            const scales = createBarScales([a, b], ['a'], dimensions, { barLayout: 'stacked' })
            const stacks = computeStackData([a, b], ['a'])

            const bottomBars = computeSeriesBars({
                series: a,
                labels: ['a'],
                scales,
                layout: 'stacked',
                isHorizontal: false,
                stackedBand: stacks.get('a'),
                isTopOfStack: false,
            })
            const topBars = computeSeriesBars({
                series: b,
                labels: ['a'],
                scales,
                layout: 'stacked',
                isHorizontal: false,
                stackedBand: stacks.get('b'),
                isTopOfStack: true,
            })
            expect(bottomBars[0]?.corners).toEqual({})
            expect(topBars[0]?.corners).toEqual({ topLeft: true, topRight: true })
        })

        it('throws when stackedBand is omitted for non-grouped layouts', () => {
            const s = makeSeries({ key: 's', data: [10] })
            const scales = createBarScales([s], ['a'], dimensions, { barLayout: 'stacked' })
            expect(() =>
                computeSeriesBars({
                    series: s,
                    labels: ['a'],
                    scales,
                    layout: 'stacked',
                    isHorizontal: false,
                    isTopOfStack: true,
                })
            ).toThrow(/stackedBand is required/)
        })
    })

    describe('computeSeriesBars — null handling', () => {
        it('returns null for null/NaN data points but preserves dataIndex order', () => {
            const labels = ['a', 'b', 'c']
            const s = makeSeries({ key: 's', data: [10, NaN, 20] })
            const scales = createBarScales([s], labels, dimensions, { barLayout: 'grouped' })
            const bars = computeSeriesBars({
                series: s,
                labels,
                scales,
                layout: 'grouped',
                isHorizontal: false,
                isTopOfStack: false,
            })
            expect(bars).toHaveLength(3)
            expect(bars[0]?.dataIndex).toBe(0)
            expect(bars[1]).toBeNull()
            expect(bars[2]?.dataIndex).toBe(2)
        })
    })
})
