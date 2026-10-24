import type { ChartDimensions } from '../../core/types'
import {
    computeHistogramLayout,
    estimateHistogramPercentile,
    histogramColumnAtPixel,
    histogramRangeToPixels,
    prepareHistogramBins,
    snapPixelRangeToBins,
} from './histogram-layout'
import type { HistogramEdges, HistogramScaleType } from './histogram-layout'

const DIMENSIONS: ChartDimensions = {
    width: 800,
    height: 400,
    plotLeft: 0,
    plotTop: 0,
    plotWidth: 800,
    plotHeight: 400,
}

function layoutOf(
    bins: HistogramEdges[],
    data: number[][],
    options: { xScaleType?: HistogramScaleType; minBarHeight?: number } = {}
): ReturnType<typeof computeHistogramLayout> {
    return computeHistogramLayout({
        bins,
        series: data.map((d) => ({ data: d })),
        dimensions: DIMENSIONS,
        ...options,
    })
}

describe('histogram layout', () => {
    it.each<[string, HistogramScaleType, HistogramEdges[], [number, number][]]>([
        [
            'linear widths follow bin widths',
            'linear',
            [
                { start: 0, end: 10 },
                { start: 10, end: 30 },
                { start: 30, end: 40 },
            ],
            [
                [0, 200],
                [200, 600],
                [600, 800],
            ],
        ],
        [
            'log widths follow the ratio of the edges',
            'log',
            [
                { start: 1, end: 2 },
                { start: 2, end: 5 },
                { start: 5, end: 10 },
            ],
            [
                [0, 241],
                [241, 559],
                [559, 800],
            ],
        ],
        [
            'a log bin starting at zero borrows the first positive bin ratio',
            'log',
            [
                { start: 0, end: 1 },
                { start: 1, end: 10 },
                { start: 10, end: 100 },
            ],
            [
                [0, 267],
                [267, 533],
                [533, 800],
            ],
        ],
    ])('places bins at their real edges: %s', (_, xScaleType, bins, expected) => {
        const layout = layoutOf(bins, [bins.map(() => 1)], { xScaleType })
        expect(layout.bins.map((bin) => [bin.x0, bin.x1])).toEqual(expected)
    })

    it('leaves a bin ending at or below zero off a log axis but keeps it in the totals', () => {
        const layout = layoutOf(
            [
                { start: -5, end: 0 },
                { start: 1, end: 10 },
            ],
            [[4, 6]],
            { xScaleType: 'log' }
        )
        expect(layout.bins.map((bin) => bin.index)).toEqual([1])
        expect(layout.grandTotal).toBe(10)
    })

    it('stacks series, keeps an empty bin as a column with no bar, and floors a tiny bin', () => {
        const layout = layoutOf(
            [
                { start: 0, end: 10 },
                { start: 10, end: 20 },
                { start: 20, end: 30 },
            ],
            [
                [600, 0, 1],
                [400, 0, 0],
            ],
            { minBarHeight: 2 }
        )
        expect(layout.bins).toHaveLength(3)
        const byBin = (binIndex: number): { y: number; height: number; seriesIndex: number }[] =>
            layout.segments
                .filter((s) => layout.bins[s.column].index === binIndex)
                .map(({ y, height, seriesIndex }) => ({ y, height, seriesIndex }))
        expect(byBin(0)).toEqual([
            { seriesIndex: 0, y: 160, height: 240 },
            { seriesIndex: 1, y: 0, height: 160 },
        ])
        expect(byBin(1)).toEqual([])
        expect(byBin(2)).toEqual([{ seriesIndex: 0, y: 398, height: 2 }])
    })

    it('merges bins narrower than a pixel into columns so a one-bin spike still draws and hovers', () => {
        const bins = Array.from({ length: 2000 }, (_, i) => ({ start: i, end: i + 1 }))
        const counts = bins.map((_, i) => (i === 1001 ? 100 : 0))
        const layout = layoutOf(bins, [counts])

        expect(layout.columnOf.every((column) => column >= 0)).toBe(true)
        expect(layout.bins.length).toBeLessThanOrEqual(DIMENSIONS.plotWidth)
        const spike = layout.bins[layout.columnOf[1001]]
        expect(spike.index).toBeLessThanOrEqual(1001)
        expect(spike.lastIndex).toBeGreaterThanOrEqual(1001)
        expect(layout.segments.slice(spike.segmentStart, spike.segmentEnd)).toEqual([
            expect.objectContaining({ y: 0, height: 400 }),
        ])
        expect(histogramColumnAtPixel(layout, (spike.x0 + spike.x1) / 2)).toBe(spike)
    })

    it.each<[string, HistogramScaleType, { min: number; max: number }, { x0: number; x1: number } | null]>([
        ['maps a range inside the domain', 'linear', { min: 10, max: 30 }, { x0: 200, x1: 600 }],
        ['clamps a range that overhangs the domain', 'linear', { min: -10, max: 50 }, { x0: 0, x1: 800 }],
        ['clamps a zero lower edge to a log domain', 'log', { min: 0, max: 10 }, { x0: 0, x1: 400 }],
        ['returns null for a range outside the domain', 'linear', { min: 50, max: 60 }, null],
    ])('selection pixels: %s', (_, xScaleType, range, expected) => {
        const bins =
            xScaleType === 'log'
                ? [
                      { start: 1, end: 10 },
                      { start: 10, end: 100 },
                  ]
                : [
                      { start: 0, end: 10 },
                      { start: 10, end: 40 },
                  ]
        const pixels = histogramRangeToPixels(layoutOf(bins, [[1, 1]], { xScaleType }), range)
        expect(pixels && { x0: Math.round(pixels.x0), x1: Math.round(pixels.x1) }).toEqual(expected)
    })

    it('sorts bins, trims an overlapping start, and drops empty or invalid bins', () => {
        const prepared = prepareHistogramBins([
            { start: 20, end: 30 },
            { start: 0, end: 10 },
            { start: 5, end: 15 },
            { start: 40, end: 40 },
            { start: NaN, end: 50 },
            { start: 12, end: 14 },
        ])
        expect(prepared.map(({ start, end, sourceIndex }) => [start, end, sourceIndex])).toEqual([
            [0, 10, 1],
            [10, 15, 2],
            [20, 30, 0],
        ])
    })

    describe('pixel hit-testing and snapping', () => {
        // Columns at [0,200) [200,400) and, after a gap, [600,800).
        const layout = layoutOf(
            [
                { start: 0, end: 10 },
                { start: 10, end: 20 },
                { start: 30, end: 40 },
            ],
            [[1, 1, 1]]
        )

        it.each([
            [100, 0],
            [200, 1],
            [500, -1],
            [799, 2],
        ])('resolves x=%d to bin %d', (x, expected) => {
            expect(histogramColumnAtPixel(layout, x)?.index ?? -1).toBe(expected)
        })

        it.each<[string, number, number, [number, number] | null]>([
            ['snaps outward to whole bins', 150, 250, [0, 20]],
            ['ignores drag direction', 250, 150, [0, 20]],
            ['treats a span ending on an edge as excluding the next bin', 50, 200, [0, 10]],
            ['skips a gap at either end', 300, 700, [10, 40]],
            ['covers nothing inside a gap', 450, 550, null],
        ])('%s', (_, x0, x1, expected) => {
            const snapped = snapPixelRangeToBins(layout, x0, x1)
            expect(snapped ? [snapped.first.start, snapped.last.end] : null).toEqual(expected)
        })
    })

    const QUARTER_BINS = [
        { start: 0, end: 10 },
        { start: 10, end: 20 },
        { start: 20, end: 30 },
        { start: 30, end: 40 },
    ]

    it.each<[string, number[], number, number]>([
        ['interpolates inside the crossing bin', [10, 10, 0, 80], 50, 33.75],
        ['starts at the first non-empty bin for p0', [0, 10, 0, 0], 0, 10],
        ['ends at the last non-empty bin for p100', [5, 5, 0, 0], 100, 20],
    ])('percentile estimate %s', (_, totals, percentile, expected) => {
        expect(estimateHistogramPercentile(QUARTER_BINS, totals, percentile)).toBeCloseTo(expected)
    })

    it('has no percentile estimate without samples', () => {
        expect(estimateHistogramPercentile(QUARTER_BINS, [0, 0, 0, 0], 50)).toBeUndefined()
    })
})
