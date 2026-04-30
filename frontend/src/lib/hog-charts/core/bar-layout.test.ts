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

        it('returns no rounding when shouldRoundCap is false', () => {
            expect(cornersFor(false, true, false)).toEqual({})
            expect(cornersFor(true, false, false)).toEqual({})
        })
    })

    describe('computeSeriesBars — grouped', () => {
        it('lays out positive grouped bars from baseline upward', () => {
            const labels = ['a', 'b']
            const a = makeSeries({ key: 'a', data: [10, 20] })
            const b = makeSeries({ key: 'b', data: [5, 15] })
            const scales = createBarScales([a, b], labels, dimensions, { barLayout: 'grouped' })
            const bars = computeSeriesBars(a, labels, scales, 'grouped', false, undefined, false)
            expect(bars).toHaveLength(2)
            expect(bars[0]?.dataIndex).toBe(0)
            expect(bars[0]?.height).toBeGreaterThan(0)
            // Vertical: bar.y should be smaller than baseline pixel since positive values map up.
            const baselinePixel = scales.value(0)
            expect(bars[0]!.y).toBeLessThan(baselinePixel)
            expect(bars[0]!.y + bars[0]!.height).toBeCloseTo(baselinePixel, 5)
        })

        it('flips corners and origin for negative grouped bars', () => {
            const labels = ['a']
            const s = makeSeries({ key: 's', data: [-10] })
            const scales = createBarScales([s], labels, dimensions, { barLayout: 'grouped' })
            const bars = computeSeriesBars(s, labels, scales, 'grouped', false, undefined, false)
            expect(bars[0]?.corners).toEqual({ bottomLeft: true, bottomRight: true })
            const baselinePixel = scales.value(0)
            // Negative values draw below the baseline; bar.y is at the baseline.
            expect(bars[0]!.y).toBeCloseTo(baselinePixel, 5)
        })

        it('produces band-axis-y / value-axis-x rects in horizontal grouped mode', () => {
            const labels = ['a']
            const s = makeSeries({ key: 's', data: [10] })
            const scales = createBarScales([s], labels, dimensions, {
                barLayout: 'grouped',
                axisOrientation: 'horizontal',
            })
            const bars = computeSeriesBars(s, labels, scales, 'grouped', true, undefined, false)
            expect(bars[0]?.corners).toEqual({ topRight: true, bottomRight: true })
            const baselinePixel = scales.value(0)
            expect(bars[0]!.x).toBeCloseTo(baselinePixel, 5)
            expect(bars[0]!.width).toBeGreaterThan(0)
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

            const bars = computeSeriesBars(b, labels, scales, 'stacked', false, stackB, true)
            expect(bars).toHaveLength(2)
            // Stacked bar height must equal pixel distance between band top and bottom.
            const expectedHeight0 = Math.abs(scales.value(stackB.top[0]) - scales.value(stackB.bottom[0]))
            expect(bars[0]!.height).toBeCloseTo(expectedHeight0, 5)
        })

        it('only rounds the top stack layer', () => {
            const labels = ['a']
            const a = makeSeries({ key: 'a', data: [10] })
            const b = makeSeries({ key: 'b', data: [5] })
            const scales = createBarScales([a, b], labels, dimensions, { barLayout: 'stacked' })
            const stacks = computeStackData([a, b], labels)

            const bottomBars = computeSeriesBars(a, labels, scales, 'stacked', false, stacks.get('a'), false)
            const topBars = computeSeriesBars(b, labels, scales, 'stacked', false, stacks.get('b'), true)
            expect(bottomBars[0]?.corners).toEqual({})
            expect(topBars[0]?.corners).toEqual({ topLeft: true, topRight: true })
        })
    })

    describe('computeSeriesBars — null handling', () => {
        it('returns null for null/NaN data points but preserves dataIndex order', () => {
            const labels = ['a', 'b', 'c']
            const s = makeSeries({ key: 's', data: [10, NaN, 20] })
            const scales = createBarScales([s], labels, dimensions, { barLayout: 'grouped' })
            const bars = computeSeriesBars(s, labels, scales, 'grouped', false, undefined, false)
            expect(bars).toHaveLength(3)
            expect(bars[0]?.dataIndex).toBe(0)
            expect(bars[1]).toBeNull()
            expect(bars[2]?.dataIndex).toBe(2)
        })
    })
})
