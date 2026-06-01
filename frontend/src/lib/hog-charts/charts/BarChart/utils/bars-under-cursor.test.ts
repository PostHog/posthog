import type { BarRect } from '../../../core/canvas-renderer'
import { computeStackData, createBarScales } from '../../../core/scales'
import { DEFAULT_Y_AXIS_ID, type Series } from '../../../core/types'
import { dimensions } from '../../../testing/jsdom'
import {
    barContainsPoint,
    barContainsPointOnBandAxis,
    computeStackEdges,
    cursorOutsideBarFillExtent,
    findVisibleStackedSegment,
} from './bars-under-cursor'

const verticalBar: BarRect = { x: 100, y: 120, width: 50, height: 200, corners: {}, dataIndex: 0 }
const horizontalBar: BarRect = { x: 60, y: 100, width: 140, height: 40, corners: {}, dataIndex: 0 }

describe('cursorOutsideBarFillExtent', () => {
    it.each([
        { desc: 'above the fill', y: 80, expected: true },
        { desc: 'on the fill cap', y: 120, expected: false },
        { desc: 'inside the fill', y: 220, expected: false },
        { desc: 'below the fill', y: 360, expected: true },
    ])('vertical bar — cursor $desc is over the track: $expected', ({ y, expected }) => {
        expect(cursorOutsideBarFillExtent(verticalBar, { x: 110, y }, false)).toBe(expected)
    })

    it.each([
        { desc: 'left of the fill', x: 40, expected: true },
        { desc: 'inside the fill', x: 120, expected: false },
        { desc: 'right of the fill', x: 300, expected: true },
    ])('horizontal bar — cursor $desc is over the track: $expected', ({ x, expected }) => {
        expect(cursorOutsideBarFillExtent(horizontalBar, { x, y: 110 }, true)).toBe(expected)
    })
})

describe('barContainsPointOnBandAxis', () => {
    it.each([
        { desc: 'inside band', y: 110, expected: true },
        { desc: 'outside band above', y: 80, expected: false },
        { desc: 'outside band below', y: 160, expected: false },
    ])('horizontal bar — ignores x, checks band (y) axis only: $desc -> $expected', ({ y, expected }) => {
        expect(barContainsPointOnBandAxis(horizontalBar, { x: -9999, y }, true)).toBe(expected)
    })

    it.each([
        { desc: 'inside band', x: 110, expected: true },
        { desc: 'outside band left', x: 80, expected: false },
        { desc: 'outside band right', x: 200, expected: false },
    ])('vertical bar — ignores y, checks band (x) axis only: $desc -> $expected', ({ x, expected }) => {
        expect(barContainsPointOnBandAxis(verticalBar, { x, y: -9999 }, false)).toBe(expected)
    })
})

describe('barContainsPoint', () => {
    it.each([
        { desc: 'inside the segment', x: 120, y: 110, expected: true },
        { desc: 'left of the segment', x: 40, y: 110, expected: false },
        { desc: 'right of the segment', x: 300, y: 110, expected: false },
        { desc: 'inside x but outside band', x: 120, y: 80, expected: false },
    ])('horizontal bar — $desc -> $expected', ({ x, y, expected }) => {
        expect(barContainsPoint(horizontalBar, { x, y })).toBe(expected)
    })

    it.each([
        { desc: 'inside the segment', x: 110, y: 220, expected: true },
        { desc: 'above the segment', x: 110, y: 80, expected: false },
        { desc: 'below the segment', x: 110, y: 360, expected: false },
        { desc: 'inside y but outside band', x: 80, y: 220, expected: false },
    ])('vertical bar — $desc -> $expected', ({ x, y, expected }) => {
        expect(barContainsPoint(verticalBar, { x, y })).toBe(expected)
    })

    // Half-open semantics on the trailing edge: matches d3 band-scale `[start, start + size)`,
    // so adjacent bars sharing a pixel boundary never both report a hit at that pixel.
    describe('boundary pixels (half-open trailing edge)', () => {
        it('vertical bar — leading edge (x=bar.x, y=bar.y) is inside', () => {
            expect(barContainsPoint(verticalBar, { x: verticalBar.x, y: verticalBar.y })).toBe(true)
        })

        it('vertical bar — trailing edge (x=bar.x+width, y=bar.y+height) is outside', () => {
            expect(
                barContainsPoint(verticalBar, {
                    x: verticalBar.x + verticalBar.width,
                    y: verticalBar.y + verticalBar.height,
                })
            ).toBe(false)
        })

        it('horizontal bar — leading edge (x=bar.x, y=bar.y) is inside', () => {
            expect(barContainsPoint(horizontalBar, { x: horizontalBar.x, y: horizontalBar.y })).toBe(true)
        })

        it('horizontal bar — trailing edge (x=bar.x+width, y=bar.y+height) is outside', () => {
            expect(
                barContainsPoint(horizontalBar, {
                    x: horizontalBar.x + horizontalBar.width,
                    y: horizontalBar.y + horizontalBar.height,
                })
            ).toBe(false)
        })
    })
})

describe('computeStackEdges', () => {
    const series = (key: string, data: number[]): Pick<Series, 'key' | 'visibility' | 'yAxisId' | 'data'> => ({
        key,
        data,
    })

    it('picks the bottommost and topmost non-zero segment per band', () => {
        const { topKeyAtIndex, bottomKeyAtIndex } = computeStackEdges(
            [series('value', [100, 55]), series('filler', [0, 45])],
            2
        )
        expect(bottomKeyAtIndex.get(DEFAULT_Y_AXIS_ID)).toEqual(['value', 'value'])
        expect(topKeyAtIndex.get(DEFAULT_Y_AXIS_ID)).toEqual(['value', 'filler'])
    })

    it('skips excluded series and treats zero/non-finite as absent', () => {
        const excluded: Pick<Series, 'key' | 'visibility' | 'yAxisId' | 'data'> = {
            key: 'hidden',
            data: [10],
            visibility: { excluded: true },
        }
        const { topKeyAtIndex, bottomKeyAtIndex } = computeStackEdges([excluded, series('a', [0]), series('b', [7])], 1)
        expect(bottomKeyAtIndex.get(DEFAULT_Y_AXIS_ID)).toEqual(['b'])
        expect(topKeyAtIndex.get(DEFAULT_Y_AXIS_ID)).toEqual(['b'])
    })

    it('keys edges by yAxisId', () => {
        const left: Pick<Series, 'key' | 'visibility' | 'yAxisId' | 'data'> = { key: 'l', data: [3], yAxisId: 'left' }
        const right: Pick<Series, 'key' | 'visibility' | 'yAxisId' | 'data'> = { key: 'r', data: [4], yAxisId: 'right' }
        const { topKeyAtIndex } = computeStackEdges([left, right], 1)
        expect(topKeyAtIndex.get('left')).toEqual(['l'])
        expect(topKeyAtIndex.get('right')).toEqual(['r'])
    })
})

describe('findVisibleStackedSegment — overdraw clip', () => {
    const bandCenterX = (scales: ReturnType<typeof createBarScales>, label: string): number =>
        (scales.band(label) ?? 0) + scales.band.bandwidth() / 2

    // Genuinely stacked segments are non-overlapping slices, so hovering any segment must
    // highlight its whole rect — nextSmallerExtent must be 0 even when a sibling is shorter.
    // Regression: the clip used to subtract the shortest sibling's height, leaving a tall
    // bottom segment only partly shaded.
    it('returns nextSmallerExtent 0 for a tall bottom segment with a shorter sibling above', () => {
        const series: Series[] = [
            { key: 'bottom', label: 'Bottom', data: [30] },
            { key: 'top', label: 'Top', data: [10] },
        ]
        const labels = ['Mon']
        const scales = createBarScales(series, labels, dimensions, {
            barLayout: 'stacked',
            axisOrientation: 'vertical',
        })
        const stackedData = computeStackData(series, labels)
        const visible = findVisibleStackedSegment({
            series,
            labels,
            hoveredLabel: 'Mon',
            cursor: { x: bandCenterX(scales, 'Mon'), y: scales.value(15) },
            scales,
            layout: 'stacked',
            isHorizontal: false,
            stackedData,
            topStackedKeyByAxis: new Map(),
        })
        expect(visible?.series.key).toBe('bottom')
        expect(visible?.nextSmallerExtent).toBe(0)
    })

    // Sparse "overlap" layout: each series draws from value 0 in a shared band, smallest on
    // top. Here the clip MUST subtract the next-smaller baseline-sharing segment so the
    // highlight doesn't paint over the slice drawn in front of it.
    it('returns the next-smaller baseline-sharing extent for the overlap layout', () => {
        const series: Series[] = [
            { key: 'big', label: 'Big', data: [100, 0] },
            { key: 'small', label: 'Small', data: [0, 20] },
        ]
        const labels = ['band', 'band']
        const scales = createBarScales(series, labels, dimensions, {
            barLayout: 'stacked',
            axisOrientation: 'horizontal',
        })
        const stackedData = computeStackData(series, labels)
        const bandCenterY = (scales.band('band') ?? 0) + scales.band.bandwidth() / 2
        const visible = findVisibleStackedSegment({
            series,
            labels,
            hoveredLabel: 'band',
            cursor: { x: scales.value(75), y: bandCenterY },
            scales,
            layout: 'stacked',
            isHorizontal: true,
            stackedData,
            topStackedKeyByAxis: new Map(),
        })
        const smallWidth = Math.abs(scales.value(20) - scales.value(0))
        expect(visible?.series.key).toBe('big')
        expect(visible?.nextSmallerExtent).toBeCloseTo(smallWidth, 5)
    })
})
