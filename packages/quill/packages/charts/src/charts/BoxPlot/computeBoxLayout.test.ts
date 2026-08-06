import { createBarScales } from '../../core/scales'
import type { ChartDimensions } from '../../core/types'
import { makeSeries } from '../../testing'
import { computeBoxRect, computeSeriesBoxes } from './computeBoxLayout'
import type { BoxPlotDatum } from './types'

const PIXEL_TEST_DIMENSIONS: ChartDimensions = {
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

// Synthetic min/max samples flow into `seriesValueRange` via the `stackedSeries` option
// so the y-domain spans whiskers, not just medians — exactly the same trick the BoxPlot
// component uses at the component layer.
function makeScales(
    labels: string[],
    seriesSpec: { key: string; data: BoxPlotDatum[] }[],
    barLayout: 'grouped' | 'stacked',
    dims = PIXEL_TEST_DIMENSIONS
): ReturnType<typeof createBarScales> {
    const coloredSeries = seriesSpec.map((s) => makeSeries({ key: s.key, data: [0] }))
    const valueRange = seriesSpec.flatMap((s) => [
        { key: `${s.key}__min`, label: s.key, data: s.data.map((d) => d.min) },
        { key: `${s.key}__max`, label: s.key, data: s.data.map((d) => d.max) },
    ])
    return createBarScales(coloredSeries, labels, dims, {
        barLayout,
        axisOrientation: 'vertical',
        stackedSeries: valueRange,
    })
}

describe('computeBoxRect', () => {
    it('puts the box top at p75 and bottom at p25 (y-axis inverted)', () => {
        const data = [datum({ min: 0, p25: 20, median: 50, mean: 55, p75: 80, max: 100 })]
        const scales = makeScales(['Mon'], [{ key: 'a', data }], 'stacked')
        const box = computeBoxRect({
            seriesKey: 'a',
            label: 'Mon',
            dataIndex: 0,
            datum: data[0]!,
            scales,
            grouped: false,
        })!
        expect(box).not.toBeNull()
        // y-axis is inverted, so the p75 pixel is *smaller* than the p25 pixel
        expect(box.top).toBe(scales.value(80))
        expect(box.bottom).toBe(scales.value(20))
        expect(box.top).toBeLessThan(box.bottom)
    })

    it('positions the median line and mean marker at their values', () => {
        const data = [datum({ p25: 20, median: 50, mean: 60, p75: 80 })]
        const scales = makeScales(['Mon'], [{ key: 'a', data }], 'stacked')
        const box = computeBoxRect({
            seriesKey: 'a',
            label: 'Mon',
            dataIndex: 0,
            datum: data[0]!,
            scales,
            grouped: false,
        })!
        expect(box.medianY).toBeCloseTo(scales.value(50), 5)
        expect(box.mean.y).toBeCloseTo(scales.value(60), 5)
        expect(box.mean.x).toBeCloseTo(box.x + box.width / 2, 5)
    })

    it('extends whiskers to min and max', () => {
        const data = [datum({ min: 5, p25: 20, median: 50, mean: 55, p75: 80, max: 95 })]
        const scales = makeScales(['Mon'], [{ key: 'a', data }], 'stacked')
        const box = computeBoxRect({
            seriesKey: 'a',
            label: 'Mon',
            dataIndex: 0,
            datum: data[0]!,
            scales,
            grouped: false,
        })!
        expect(box.whiskerTop).toBeCloseTo(scales.value(95), 5)
        expect(box.whiskerBottom).toBeCloseTo(scales.value(5), 5)
        expect(box.whiskerTop).toBeLessThan(box.top)
        expect(box.whiskerBottom).toBeGreaterThan(box.bottom)
    })

    it('uses the full band width when not grouped', () => {
        const data = [datum()]
        const scales = makeScales(['Mon'], [{ key: 'a', data }], 'stacked')
        const box = computeBoxRect({
            seriesKey: 'a',
            label: 'Mon',
            dataIndex: 0,
            datum: data[0]!,
            scales,
            grouped: false,
        })!
        expect(box.width).toBeCloseTo(scales.band.bandwidth(), 5)
        expect(box.x).toBeCloseTo(scales.band('Mon')!, 5)
    })

    it('uses the group sub-band when grouped', () => {
        const aData = [datum()]
        const bData = [datum()]
        const scales = makeScales(
            ['Mon'],
            [
                { key: 'a', data: aData },
                { key: 'b', data: bData },
            ],
            'grouped'
        )
        const boxA = computeBoxRect({
            seriesKey: 'a',
            label: 'Mon',
            dataIndex: 0,
            datum: aData[0]!,
            scales,
            grouped: true,
        })!
        const boxB = computeBoxRect({
            seriesKey: 'b',
            label: 'Mon',
            dataIndex: 0,
            datum: bData[0]!,
            scales,
            grouped: true,
        })!
        expect(boxA.width).toBeCloseTo(scales.group!.bandwidth(), 5)
        expect(boxB.width).toBeCloseTo(scales.group!.bandwidth(), 5)
        // Two grouped boxes within a single band must not overlap on the band axis.
        expect(boxA.x + boxA.width).toBeLessThanOrEqual(boxB.x + 0.0001)
    })

    it('returns null for unknown labels (band scale miss)', () => {
        const data = [datum()]
        const scales = makeScales(['Mon'], [{ key: 'a', data }], 'stacked')
        const box = computeBoxRect({
            seriesKey: 'a',
            label: 'Friday',
            dataIndex: 0,
            datum: data[0]!,
            scales,
            grouped: false,
        })
        expect(box).toBeNull()
    })

    it('returns null when grouped but the series is missing from the group scale', () => {
        const data = [datum()]
        const scales = makeScales(['Mon'], [{ key: 'a', data }], 'stacked')
        // Stacked layout has no group scale — caller asking for grouped should miss cleanly.
        const box = computeBoxRect({
            seriesKey: 'a',
            label: 'Mon',
            dataIndex: 0,
            datum: data[0]!,
            scales,
            grouped: true,
        })
        expect(box).toBeNull()
    })

    it('returns null when any of the six numbers is non-finite', () => {
        const data = [datum({ p25: Number.NaN })]
        const scales = makeScales(['Mon'], [{ key: 'a', data: [datum()] }], 'stacked')
        const box = computeBoxRect({
            seriesKey: 'a',
            label: 'Mon',
            dataIndex: 0,
            datum: data[0]!,
            scales,
            grouped: false,
        })
        expect(box).toBeNull()
    })

    it('collapses to a flat box when all-equal values', () => {
        const data = [{ min: 50, p25: 50, median: 50, mean: 50, p75: 50, max: 50 }]
        const scales = makeScales(['Mon'], [{ key: 'a', data }], 'stacked')
        const box = computeBoxRect({
            seriesKey: 'a',
            label: 'Mon',
            dataIndex: 0,
            datum: data[0]!,
            scales,
            grouped: false,
        })!
        expect(box.top).toBeCloseTo(box.bottom, 5)
        expect(box.whiskerTop).toBeCloseTo(box.top, 5)
        expect(box.whiskerBottom).toBeCloseTo(box.bottom, 5)
        expect(box.medianY).toBeCloseTo(box.top, 5)
    })

    it('handles degenerate inverted p25 > p75 by always reporting top < bottom', () => {
        const data = [{ min: 0, p25: 80, median: 50, mean: 50, p75: 20, max: 100 }]
        const scales = makeScales(['Mon'], [{ key: 'a', data: [datum()] }], 'stacked')
        const box = computeBoxRect({
            seriesKey: 'a',
            label: 'Mon',
            dataIndex: 0,
            datum: data[0]!,
            scales,
            grouped: false,
        })!
        expect(box.top).toBeLessThanOrEqual(box.bottom)
    })

    it('preserves dataIndex on the result', () => {
        const data: BoxPlotDatum[] = [datum(), datum(), datum()]
        const scales = makeScales(['Mon', 'Tue', 'Wed'], [{ key: 'a', data }], 'stacked')
        const box = computeBoxRect({
            seriesKey: 'a',
            label: 'Wed',
            dataIndex: 2,
            datum: data[2],
            scales,
            grouped: false,
        })!
        expect(box.dataIndex).toBe(2)
    })
})

describe('computeSeriesBoxes', () => {
    it('drops null and unrenderable indices', () => {
        const labels = ['Mon', 'Tue', 'Wed']
        const data: (BoxPlotDatum | null)[] = [datum(), null, datum()]
        // makeScales only needs the value-range samples — pass the non-null entries.
        const scales = makeScales(labels, [{ key: 'a', data: [datum(), datum()] }], 'stacked')
        const boxes = computeSeriesBoxes({
            seriesKey: 'a',
            data,
            labels,
            scales,
            grouped: false,
        })
        expect(boxes.map((b) => b.dataIndex)).toEqual([0, 2])
    })

    it('emits one box per non-null index', () => {
        const labels = ['Mon', 'Tue', 'Wed']
        const data: BoxPlotDatum[] = [datum(), datum(), datum()]
        const scales = makeScales(labels, [{ key: 'a', data }], 'stacked')
        const boxes = computeSeriesBoxes({
            seriesKey: 'a',
            data,
            labels,
            scales,
            grouped: false,
        })
        expect(boxes).toHaveLength(3)
    })

    it('handles a single-point series (one label)', () => {
        const labels = ['only']
        const data: BoxPlotDatum[] = [datum()]
        const scales = makeScales(labels, [{ key: 'a', data }], 'stacked')
        const boxes = computeSeriesBoxes({
            seriesKey: 'a',
            data,
            labels,
            scales,
            grouped: false,
        })
        expect(boxes).toHaveLength(1)
        expect(boxes[0].dataIndex).toBe(0)
    })
})
