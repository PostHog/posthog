import { computeStackData, createBarScales } from '../../../core/scales'
import type { PointClickData, Series } from '../../../core/types'
import { dimensions } from '../../../testing/jsdom'
import type { BarLayout } from './bars-under-cursor'
import { resolveClickedBarSeries } from './resolve-clicked-bar-series'

describe('resolveClickedBarSeries', () => {
    const crossSeriesAt = <Meta>(series: Series<Meta>[], dataIndex: number): PointClickData<Meta>['crossSeriesData'] =>
        series.map((s) => ({ series: s, value: s.data[dataIndex] ?? 0 }))

    const baseClickData = <Meta>(
        series: Series<Meta>[],
        dataIndex: number,
        label: string,
        cursor: { x: number; y: number } | null
    ): PointClickData<Meta> => ({
        seriesIndex: 0,
        dataIndex,
        series: series[0],
        value: series[0].data[dataIndex] ?? 0,
        label,
        crossSeriesData: crossSeriesAt(series, dataIndex),
        cursor,
    })

    it('returns null (passthrough) when the cursor is unavailable', () => {
        const series: Series[] = [{ key: 'a', label: 'A', data: [10] }]
        const scales = createBarScales(series, ['x'], dimensions, { barLayout: 'grouped', axisOrientation: 'vertical' })
        const result = resolveClickedBarSeries({
            clickData: baseClickData(series, 0, 'x', null),
            scales,
            barLayout: 'grouped',
            isHorizontal: false,
            stackedData: undefined,
            topStackedKeyByAxis: new Map(),
            series,
            labels: ['x'],
        })
        expect(result).toBeNull()
    })

    describe('grouped layout', () => {
        const labels = ['x', 'y']
        // `a` is the tallest at x (domain max), `b` is short so the track region above it is testable.
        const series: Series[] = [
            { key: 'a', label: 'A', data: [100, 50] },
            { key: 'b', label: 'B', data: [20, 30] },
            { key: 'c', label: 'C', data: [60, 40] },
        ]
        const scales = createBarScales(series, labels, dimensions, {
            barLayout: 'grouped',
            axisOrientation: 'vertical',
        })
        const subBandCenterX = (key: string): number =>
            scales.band('x')! + scales.group!(key)! + scales.group!.bandwidth() / 2
        const fillCenterY = (value: number): number => (scales.value(value) + scales.value(0)) / 2

        const resolve = (cursor: { x: number; y: number }): PointClickData | null =>
            resolveClickedBarSeries({
                clickData: baseClickData(series, 0, 'x', cursor),
                scales,
                barLayout: 'grouped',
                isHorizontal: false,
                stackedData: undefined,
                topStackedKeyByAxis: new Map(),
                series,
                labels,
            })

        it.each([
            { key: 'a', seriesIndex: 0, value: 100 },
            { key: 'b', seriesIndex: 1, value: 20 },
            { key: 'c', seriesIndex: 2, value: 60 },
        ])('routes a click on the $key sub-band column to that series', ({ key, seriesIndex, value }) => {
            const result = resolve({ x: subBandCenterX(key), y: fillCenterY(value) })
            expect(result?.series.key).toBe(key)
            expect(result?.seriesIndex).toBe(seriesIndex)
            expect(result?.value).toBe(value)
            expect(result?.inTrackArea).toBe(false)
        })

        it('flags inTrackArea when the cursor is in the column but above the short bar', () => {
            const result = resolve({ x: subBandCenterX('b'), y: 0 })
            expect(result?.series.key).toBe('b')
            expect(result?.inTrackArea).toBe(true)
        })

        it('returns null when the cursor is outside every sub-band column', () => {
            expect(resolve({ x: scales.band('x')! - 100, y: fillCenterY(20) })).toBeNull()
        })
    })

    describe('stacked layout', () => {
        const labels = ['Mon']
        const series: Series[] = [
            { key: 'bottom', label: 'Bottom', data: [30] },
            { key: 'top', label: 'Top', data: [10] },
        ]
        const scales = createBarScales(series, labels, dimensions, {
            barLayout: 'stacked',
            axisOrientation: 'vertical',
        })
        const stackedData = computeStackData(series, labels)
        const bandCenterX = scales.band('Mon')! + scales.band.bandwidth() / 2

        const resolve = (layout: BarLayout, valueAtCursor: number): PointClickData | null =>
            resolveClickedBarSeries({
                clickData: baseClickData(series, 0, 'Mon', { x: bandCenterX, y: scales.value(valueAtCursor) }),
                scales,
                barLayout: layout,
                isHorizontal: false,
                stackedData,
                topStackedKeyByAxis: new Map(),
                series,
                labels,
            })

        it('routes to the bottom segment when the cursor is on the value axis below the split', () => {
            const result = resolve('stacked', 15)
            expect(result?.series.key).toBe('bottom')
            expect(result?.seriesIndex).toBe(0)
            expect(result?.value).toBe(30)
        })

        it('routes to the top segment when the cursor is above the split', () => {
            const result = resolve('stacked', 35)
            expect(result?.series.key).toBe('top')
            expect(result?.seriesIndex).toBe(1)
            expect(result?.value).toBe(10)
        })

        it('treats percent layout like stacked for routing', () => {
            expect(resolve('percent', 35)?.series.key).toBe('top')
        })
    })

    describe('sparse-overlap layout', () => {
        // Two bars sharing a band drawn from a common baseline (smallest on top). The hovered band's
        // dataIndex holds a zero for `small`; routing must re-read `small`'s value at its own column.
        const labels = ['band', 'band']
        const series: Series[] = [
            { key: 'big', label: 'Big', data: [100, 0] },
            { key: 'small', label: 'Small', data: [0, 20] },
        ]
        const scales = createBarScales(series, labels, dimensions, {
            barLayout: 'stacked',
            axisOrientation: 'horizontal',
        })
        const stackedData = computeStackData(series, labels)
        const bandCenterY = scales.band('band')! + scales.band.bandwidth() / 2

        it('re-reads the value at the visible segment own dataIndex (not the band sparse-zero cell)', () => {
            const result = resolveClickedBarSeries({
                // Clicked at the band's dataIndex 0, where `small` is a sparse zero.
                clickData: baseClickData(series, 0, 'band', { x: scales.value(10), y: bandCenterY }),
                scales,
                barLayout: 'stacked',
                isHorizontal: true,
                stackedData,
                topStackedKeyByAxis: new Map(),
                series,
                labels,
            })
            expect(result?.series.key).toBe('small')
            expect(result?.dataIndex).toBe(1)
            expect(result?.value).toBe(20)
            expect(result?.seriesIndex).toBe(1)
        })
    })
})
