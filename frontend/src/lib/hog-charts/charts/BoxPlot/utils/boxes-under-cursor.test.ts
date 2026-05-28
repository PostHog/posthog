import { createBarScales } from '../../../core/scales'
import type { ChartDimensions } from '../../../core/types'
import { makeSeries } from '../../../testing'
import type { BoxPlotDatum, BoxPlotSeries } from '../computeBoxLayout'
import { cursorInsideBoxBand, seriesKeysAtCursor } from './boxes-under-cursor'

const DIMS: ChartDimensions = {
    width: 400,
    height: 200,
    plotLeft: 0,
    plotTop: 0,
    plotWidth: 400,
    plotHeight: 200,
}

function datum(overrides: Partial<BoxPlotDatum> = {}): BoxPlotDatum {
    return { min: 0, p25: 25, median: 50, mean: 55, p75: 75, max: 100, ...overrides }
}

function makeScales(
    labels: string[],
    seriesSpec: { key: string; data: (BoxPlotDatum | null)[] }[],
    barLayout: 'grouped' | 'stacked' = seriesSpec.length > 1 ? 'grouped' : 'stacked'
): ReturnType<typeof createBarScales> {
    const coloredSeries = seriesSpec.map((s) => makeSeries({ key: s.key, data: [0] }))
    const valueRange: { key: string; label: string; data: number[] }[] = []
    for (const s of seriesSpec) {
        for (const d of s.data) {
            if (d) {
                valueRange.push({ key: `${s.key}_${valueRange.length}`, label: s.key, data: [d.min, d.max] })
            }
        }
    }
    return createBarScales(coloredSeries, labels, DIMS, {
        barLayout,
        axisOrientation: 'vertical',
        stackedSeries: valueRange,
    })
}

describe('cursorInsideBoxBand', () => {
    const box = { x: 10, width: 40 }
    it.each([
        ['cursor left of box', { x: 5 }, false],
        ['cursor on left edge', { x: 10 }, true],
        ['cursor inside box', { x: 30 }, true],
        ['cursor on right edge', { x: 50 }, true],
        ['cursor right of box', { x: 60 }, false],
    ])('%s', (_name, cursor, expected) => {
        expect(cursorInsideBoxBand(box, cursor)).toBe(expected)
    })
})

describe('seriesKeysAtCursor', () => {
    const LABELS = ['Mon', 'Tue']

    it('finds the box under the cursor in a grouped layout', () => {
        const series: BoxPlotSeries[] = [
            { key: 'a', label: 'A', data: [datum(), datum()] },
            { key: 'b', label: 'B', data: [datum(), datum()] },
        ]
        const scales = makeScales(LABELS, series)

        // Sub-band centers for series a and b in label "Mon".
        const bandStart = scales.band('Mon')!
        const groupBandwidth = scales.group!.bandwidth()
        const aCenter = bandStart + scales.group!('a')! + groupBandwidth / 2
        const bCenter = bandStart + scales.group!('b')! + groupBandwidth / 2

        const aHits = seriesKeysAtCursor({
            series,
            label: 'Mon',
            dataIndex: 0,
            cursor: { x: aCenter, y: 100 },
            scales,
            grouped: true,
        })
        const bHits = seriesKeysAtCursor({
            series,
            label: 'Mon',
            dataIndex: 0,
            cursor: { x: bCenter, y: 100 },
            scales,
            grouped: true,
        })
        expect(Array.from(aHits)).toEqual(['a'])
        expect(Array.from(bHits)).toEqual(['b'])
    })

    it('returns empty when the cursor is in a between-group gap', () => {
        const series: BoxPlotSeries[] = [
            { key: 'a', label: 'A', data: [datum(), datum()] },
            { key: 'b', label: 'B', data: [datum(), datum()] },
        ]
        const scales = makeScales(LABELS, series)
        const bandStart = scales.band('Mon')!
        // x just before the band starts — in the outer-padding gap.
        const gapX = bandStart - 5
        const hits = seriesKeysAtCursor({
            series,
            label: 'Mon',
            dataIndex: 0,
            cursor: { x: gapX, y: 100 },
            scales,
            grouped: true,
        })
        expect(hits.size).toBe(0)
    })

    it('skips excluded series', () => {
        const series: BoxPlotSeries[] = [
            { key: 'a', label: 'A', data: [datum(), datum()] },
            { key: 'b', label: 'B', data: [datum(), datum()], visibility: { excluded: true } },
        ]
        const scales = makeScales(LABELS, series, 'grouped')
        const bandStart = scales.band('Mon')!
        const groupBandwidth = scales.group!.bandwidth()
        // even at b's would-be center, b is excluded so it can't be a hit
        const bCenter = bandStart + (scales.group!('b') ?? 0) + groupBandwidth / 2
        const hits = seriesKeysAtCursor({
            series,
            label: 'Mon',
            dataIndex: 0,
            cursor: { x: bCenter, y: 100 },
            scales,
            grouped: true,
        })
        expect(hits.has('b')).toBe(false)
    })

    it('skips indices with null data', () => {
        const series: BoxPlotSeries[] = [{ key: 'a', label: 'A', data: [datum(), null] }]
        const scales = makeScales(LABELS, series, 'stacked')
        const bandStart = scales.band('Tue')!
        const cursorX = bandStart + scales.band.bandwidth() / 2
        const hits = seriesKeysAtCursor({
            series,
            label: 'Tue',
            dataIndex: 1,
            cursor: { x: cursorX, y: 100 },
            scales,
            grouped: false,
        })
        expect(hits.size).toBe(0)
    })
})
