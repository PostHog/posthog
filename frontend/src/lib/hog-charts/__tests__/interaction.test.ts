import { buildPointClickData, buildTooltipContext, findNearestIndex, isInPlotArea } from '../core/interaction'
import type { ResolveValueFn } from '../core/types'
import { dimensions, makeSeries } from '../test-helpers'

const defaultResolveValue: ResolveValueFn = (s, i) => s.data[i]

const fakeCanvasBounds = {
    x: 0,
    y: 0,
    width: 800,
    height: 400,
    top: 0,
    right: 800,
    bottom: 400,
    left: 0,
    toJSON: (): Record<string, unknown> => ({}),
} as DOMRect

describe('hog-charts interaction', () => {
    describe('findNearestIndex', () => {
        it('returns -1 for empty labels', () => {
            const xScale = (): undefined => undefined
            expect(findNearestIndex(100, [], xScale)).toBe(-1)
        })

        it('returns 0 for a single label regardless of mouseX position', () => {
            const xScale = (label: string): number | undefined => (label === 'a' ? 100 : undefined)
            expect(findNearestIndex(0, ['a'], xScale)).toBe(0)
            expect(findNearestIndex(999, ['a'], xScale)).toBe(0)
        })

        it('falls back to x=0 for undefined xScale positions and still returns a valid index', () => {
            // The implementation treats undefined xScale as 0 via `?? 0`, so positions are
            // still finite and findNearestIndex returns the nearest index rather than -1.
            const xScale = (): number | undefined => undefined
            const result = findNearestIndex(100, ['a', 'b'], xScale)
            expect(result).toBeGreaterThanOrEqual(0)
        })

        it('returns the index of the closest label when mouseX is between two points', () => {
            const xScale = (label: string): number | undefined => ({ a: 100, b: 200, c: 300 })[label]
            expect(findNearestIndex(140, ['a', 'b', 'c'], xScale)).toBe(0)
            expect(findNearestIndex(160, ['a', 'b', 'c'], xScale)).toBe(1)
        })

        it('returns the first index when mouseX is to the left of all points', () => {
            const xScale = (label: string): number | undefined => ({ a: 100, b: 200 })[label]
            expect(findNearestIndex(0, ['a', 'b'], xScale)).toBe(0)
        })

        it('returns the last index when mouseX is to the right of all points', () => {
            const xScale = (label: string): number | undefined => ({ a: 100, b: 200 })[label]
            expect(findNearestIndex(999, ['a', 'b'], xScale)).toBe(1)
        })

        it('returns the exact index when mouseX lands exactly on a point', () => {
            const xScale = (label: string): number | undefined => ({ a: 100, b: 200, c: 300 })[label]
            expect(findNearestIndex(200, ['a', 'b', 'c'], xScale)).toBe(1)
        })
    })

    describe('isInPlotArea', () => {
        it.each([
            { x: 100, y: 100, expected: true, desc: 'inside' },
            { x: dimensions.plotLeft, y: dimensions.plotTop, expected: true, desc: 'top-left corner' },
            {
                x: dimensions.plotLeft + dimensions.plotWidth,
                y: dimensions.plotTop + dimensions.plotHeight,
                expected: true,
                desc: 'bottom-right corner',
            },
            { x: dimensions.plotLeft - 1, y: 100, expected: false, desc: 'left of plotLeft' },
            {
                x: dimensions.plotLeft + dimensions.plotWidth + 1,
                y: 100,
                expected: false,
                desc: 'right of plot area',
            },
            { x: 100, y: dimensions.plotTop - 1, expected: false, desc: 'above plotTop' },
            {
                x: 100,
                y: dimensions.plotTop + dimensions.plotHeight + 1,
                expected: false,
                desc: 'below plot area',
            },
        ])('returns $expected when $desc', ({ x, y, expected }) => {
            expect(isInPlotArea(x, y, dimensions)).toBe(expected)
        })
    })

    describe('buildTooltipContext', () => {
        const xConst = (): number => 100
        const yConst = (): number => 50

        it.each([
            { index: -1, desc: 'negative dataIndex' },
            { index: 1, desc: 'dataIndex equal to labels.length' },
        ])('returns null for $desc', ({ index }) => {
            const series = [makeSeries({ key: 's1', data: [10] })]
            const result = buildTooltipContext(
                index,
                series,
                ['a'],
                xConst,
                yConst,
                fakeCanvasBounds,
                defaultResolveValue
            )
            expect(result).toBeNull()
        })

        it('returns null when xScale returns undefined for the label', () => {
            const series = [makeSeries({ key: 's1', data: [10] })]
            const xUndef = (): undefined => undefined
            const result = buildTooltipContext(0, series, ['a'], xUndef, yConst, fakeCanvasBounds, defaultResolveValue)
            expect(result).toBeNull()
        })

        it('returns a context with the correct label for a valid index', () => {
            const series = [makeSeries({ key: 's1', data: [10, 20] })]
            const xScale = (label: string): number => (label === 'b' ? 200 : 100)
            const result = buildTooltipContext(
                1,
                series,
                ['a', 'b'],
                xScale,
                yConst,
                fakeCanvasBounds,
                defaultResolveValue
            )
            expect(result?.label).toBe('b')
            expect(result?.dataIndex).toBe(1)
        })

        it('excludes hidden series from seriesData', () => {
            const visible = makeSeries({ key: 'v', data: [10] })
            const hidden = makeSeries({ key: 'h', data: [20], hidden: true })
            const result = buildTooltipContext(
                0,
                [visible, hidden],
                ['a'],
                xConst,
                yConst,
                fakeCanvasBounds,
                defaultResolveValue
            )
            expect(result?.seriesData.length).toBe(1)
            expect(result?.seriesData[0].series.key).toBe('v')
        })

        it('includes correct pixel position from xScale and minimum yScale output', () => {
            const s1 = makeSeries({ key: 's1', data: [10] })
            const s2 = makeSeries({ key: 's2', data: [50] })
            const xFixed = (): number => 150
            // s1 maps to y=80, s2 maps to y=30 — position.y should be min(80,30)=30
            const yScale = (v: number): number => (v === 10 ? 80 : 30)
            const result = buildTooltipContext(
                0,
                [s1, s2],
                ['a'],
                xFixed,
                yScale,
                fakeCanvasBounds,
                defaultResolveValue
            )
            expect(result?.position.x).toBe(150)
            expect(result?.position.y).toBe(30)
        })

        it('passes canvasBounds through to the returned context', () => {
            const series = [makeSeries({ key: 's1', data: [10] })]
            const result = buildTooltipContext(0, series, ['a'], xConst, yConst, fakeCanvasBounds, defaultResolveValue)
            expect(result?.canvasBounds).toBe(fakeCanvasBounds)
        })

        it('uses the resolveValue function to get series values', () => {
            const series = [makeSeries({ key: 's1', data: [10] })]
            const customResolve: ResolveValueFn = (): number => 999
            const result = buildTooltipContext(0, series, ['a'], xConst, yConst, fakeCanvasBounds, customResolve)
            expect(result?.seriesData[0].value).toBe(999)
        })
    })

    describe('buildPointClickData', () => {
        it.each([
            { index: -1, desc: 'negative dataIndex' },
            { index: 1, desc: 'dataIndex equal to labels.length' },
        ])('returns null for $desc', ({ index }) => {
            const series = [makeSeries({ key: 's1', data: [10] })]
            expect(buildPointClickData(index, series, ['a'], defaultResolveValue)).toBeNull()
        })

        it('returns null when all series are hidden', () => {
            const series = [makeSeries({ key: 's1', data: [10], hidden: true })]
            expect(buildPointClickData(0, series, ['a'], defaultResolveValue)).toBeNull()
        })

        it('returns click data for a valid index with a single visible series', () => {
            const series = [makeSeries({ key: 's1', data: [42] })]
            const result = buildPointClickData(0, series, ['a'], defaultResolveValue)
            expect(result).not.toBeNull()
            expect(result?.label).toBe('a')
            expect(result?.dataIndex).toBe(0)
            expect(result?.value).toBe(42)
            expect(result?.series.key).toBe('s1')
            expect(result?.seriesIndex).toBe(0)
        })

        it('uses the first visible series when multiple series are present', () => {
            const hidden = makeSeries({ key: 'h', data: [1], hidden: true })
            const visible = makeSeries({ key: 'v', data: [2] })
            const result = buildPointClickData(0, [hidden, visible], ['a'], defaultResolveValue)
            expect(result?.series.key).toBe('v')
            expect(result?.seriesIndex).toBe(1)
        })

        it('includes all visible series in crossSeriesData', () => {
            const s1 = makeSeries({ key: 's1', data: [10] })
            const s2 = makeSeries({ key: 's2', data: [20] })
            const hidden = makeSeries({ key: 'h', data: [30], hidden: true })
            const result = buildPointClickData(0, [s1, s2, hidden], ['a'], defaultResolveValue)
            expect(result?.crossSeriesData.length).toBe(2)
            expect(result?.crossSeriesData.map((d) => d.series.key)).toEqual(['s1', 's2'])
        })

        it('uses the resolveValue function for both value and crossSeriesData', () => {
            const s1 = makeSeries({ key: 's1', data: [0] })
            const s2 = makeSeries({ key: 's2', data: [0] })
            const customResolve: ResolveValueFn = (s) => (s.key === 's1' ? 111 : 222)
            const result = buildPointClickData(0, [s1, s2], ['a'], customResolve)
            expect(result?.value).toBe(111)
            expect(result?.crossSeriesData[0].value).toBe(111)
            expect(result?.crossSeriesData[1].value).toBe(222)
        })

        it('returns the correct label for a non-zero dataIndex', () => {
            const series = [makeSeries({ key: 's1', data: [10, 20, 30] })]
            const result = buildPointClickData(2, series, ['x', 'y', 'z'], defaultResolveValue)
            expect(result?.label).toBe('z')
            expect(result?.value).toBe(30)
        })
    })
})
