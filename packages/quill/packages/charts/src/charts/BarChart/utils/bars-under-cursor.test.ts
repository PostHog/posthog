import type { BarRect } from '../../../core/canvas-renderer'
import { computeStackData, createBarScales } from '../../../core/scales'
import type { Series } from '../../../core/types'
import { dimensions } from '../../../testing/jsdom'
import {
    barContainsPoint,
    barContainsPointOnBandAxis,
    cursorOutsideBarFillExtent,
    findVisibleStackedSegment,
    groupedBandSlotAtCursor,
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

describe('groupedBandSlotAtCursor', () => {
    const labels = ['x', 'y']
    const series: Series[] = [
        { key: 'a', label: 'A', data: [1, 1] },
        { key: 'b', label: 'B', data: [2, 2] },
        { key: 'c', label: 'C', data: [3, 3] },
    ]
    const grouped = createBarScales(series, labels, dimensions, { barLayout: 'grouped', axisOrientation: 'vertical' })
    const start = grouped.band('x')!
    const bandwidth = grouped.group!.bandwidth()
    const slotXOf = (key: string): number => start + grouped.group!(key)!
    const centerOf = (key: string): number => slotXOf(key) + bandwidth / 2
    const farLeft = start - 1000
    const farRight = start + 1000

    it.each(['a', 'b', 'c'])('returns the slot of the bar the cursor sits inside (%s)', (key) => {
        expect(groupedBandSlotAtCursor(grouped, 'x', centerOf(key))).toEqual({ x: slotXOf(key), width: bandwidth })
    })

    it('snaps to the nearest bar by center when the cursor falls outside the bars', () => {
        expect(groupedBandSlotAtCursor(grouped, 'x', farLeft)?.x).toBeCloseTo(slotXOf('a'), 5)
        expect(groupedBandSlotAtCursor(grouped, 'x', farRight)?.x).toBeCloseTo(slotXOf('c'), 5)
    })

    it('returns undefined for an unknown label', () => {
        expect(groupedBandSlotAtCursor(grouped, 'missing', start)).toBeUndefined()
    })

    it('returns undefined when there is no group scale (non-grouped layout)', () => {
        const stacked = createBarScales(series, labels, dimensions, { barLayout: 'stacked' })
        expect(groupedBandSlotAtCursor(stacked, 'x', start)).toBeUndefined()
    })
})
