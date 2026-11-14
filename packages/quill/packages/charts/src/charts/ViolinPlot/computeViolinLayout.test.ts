import { createBarScales, type BarScaleSet } from '../../core/scales'
import type { ChartDimensions } from '../../core/types'
import { makeSeries } from '../../testing'
import { computeSeriesViolins, computeViolinRect, densityProfile, summarizeViolin } from './computeViolinLayout'
import type { ViolinPlotDatum } from './types'

const DIMS: ChartDimensions = {
    width: 400,
    height: 200,
    plotLeft: 0,
    plotTop: 0,
    plotWidth: 400,
    plotHeight: 200,
}

const LABELS = ['Mon', 'Tue']

function scalesFor(
    data: (ViolinPlotDatum | null)[],
    options: { scaleType?: 'linear' | 'log'; range?: [number, number] } = {}
): BarScaleSet {
    const finite = data.flatMap((datum) => datum?.values.filter(Number.isFinite) ?? [])
    const [min, max] = options.range ?? [Math.min(...finite), Math.max(...finite)]
    return createBarScales([makeSeries({ key: 'a', data: LABELS.map(() => 0) })], LABELS, DIMS, {
        barLayout: 'stacked',
        axisOrientation: 'vertical',
        scaleType: options.scaleType,
        stackedSeries: [
            { key: 'a__min', label: 'a', data: [min] },
            { key: 'a__max', label: 'a', data: [max] },
        ],
    })
}

const CLUSTER: ViolinPlotDatum = { values: [8, 9, 10, 10, 11, 11, 11, 12, 12, 13] }

describe('computeViolinLayout', () => {
    describe('summarizeViolin', () => {
        it('leaves values that are not positive out of the summary on a log axis', () => {
            const summary = summarizeViolin({ values: [-1, 0, 10, 100, 1000] }, true)

            expect(summary).toMatchObject({ count: 3, min: 10, median: 100, max: 1000 })
            expect(summary?.mean).toBeCloseTo(370)
        })

        it('keeps values that are not positive in the summary on a linear axis', () => {
            expect(summarizeViolin({ values: [-1, 0, 10, 100, 1000] })).toMatchObject({ count: 5, min: -1, median: 10 })
        })

        it('summarizes the observations', () => {
            expect(summarizeViolin({ values: [1, 2, 3, 4, 5] })).toEqual({
                count: 5,
                min: 1,
                p25: 2,
                median: 3,
                mean: 3,
                p75: 4,
                max: 5,
            })
        })

        it('interpolates between observations for the quartiles', () => {
            const summary = summarizeViolin({ values: [4, 1, 3, 2] })

            expect(summary).toMatchObject({ p25: 1.75, median: 2.5, p75: 3.25 })
        })

        it('ignores values that are not finite', () => {
            const summary = summarizeViolin({ values: [1, Number.NaN, 3, Number.POSITIVE_INFINITY] })

            expect(summary).toMatchObject({ count: 2, min: 1, max: 3, mean: 2 })
        })

        it.each([
            ['no observations', { values: [] }],
            ['only non-finite observations', { values: [Number.NaN, Number.NEGATIVE_INFINITY] }],
        ])('returns null for %s', (_name, datum) => {
            expect(summarizeViolin(datum)).toBeNull()
        })
    })

    describe('densityProfile', () => {
        const SORTED = [8, 9, 10, 10, 11, 11, 11, 12, 12, 13]

        it('samples evenly from the low to the high end', () => {
            const profile = densityProfile(SORTED, 0, 20, 1, 5)

            expect(profile.map((point) => point.value)).toEqual([0, 5, 10, 15, 20])
        })

        it('peaks where the observations cluster', () => {
            const profile = densityProfile(SORTED, 5, 16, 1, 45)
            const peak = profile.reduce((widest, point) => (point.density > widest.density ? point : widest))

            expect(peak.value).toBeGreaterThan(10)
            expect(peak.value).toBeLessThan(12)
        })

        it('is zero beyond the reach of every observation', () => {
            const profile = densityProfile(SORTED, 0, 30, 1, 31)

            expect(profile[0].density).toBe(0)
            expect(profile[30].density).toBe(0)
        })

        it('matches the unwindowed sum where the kernel is not truncated', () => {
            const [point] = densityProfile([1, 2], 1.5, 1.5, 1, 1)
            const expected = 2 * Math.exp(-0.5 * 0.5 ** 2)

            expect(point.density).toBeCloseTo(expected, 12)
        })
    })

    describe('computeViolinRect', () => {
        function rectFor(
            datum: ViolinPlotDatum,
            overrides: { label?: string; showPoints?: boolean } = {}
        ): ReturnType<typeof computeViolinRect> {
            return computeViolinRect({
                seriesKey: 'a',
                label: overrides.label ?? 'Mon',
                dataIndex: 0,
                datum,
                scales: scalesFor([datum]),
                grouped: false,
                showPoints: overrides.showPoints ?? true,
            })
        }

        it('fills the slot at its widest and tapers to the tips', () => {
            const rect = rectFor(CLUSTER)!
            const widest = Math.max(...rect.outline.map((point) => point.halfWidth))

            expect(widest).toBeCloseTo((rect.width / 2) * 0.95, 6)
            expect(rect.outline[0].halfWidth).toBeLessThan(widest / 2)
            expect(rect.outline[rect.outline.length - 1].halfWidth).toBeLessThan(widest / 2)
        })

        it('orders the outline from the lowest value to the highest, which is the larger pixel first', () => {
            const rect = rectFor(CLUSTER)!
            const ys = rect.outline.map((point) => point.y)

            expect(ys).toEqual([...ys].sort((a, b) => b - a))
        })

        it('keeps the outline inside the plot', () => {
            const rect = rectFor({ values: [0, 0, 1, 100] })!

            for (const point of rect.outline) {
                expect(point.y).toBeGreaterThanOrEqual(DIMS.plotTop - 1e-6)
                expect(point.y).toBeLessThanOrEqual(DIMS.plotTop + DIMS.plotHeight + 1e-6)
            }
        })

        it('centers the violin and the mean marker on the slot', () => {
            const rect = rectFor(CLUSTER)!

            expect(rect.centerX).toBeCloseTo(rect.x + rect.width / 2, 6)
            expect(rect.mean.x).toBe(rect.centerX)
        })

        it('places the median pixel between the lowest and highest observation', () => {
            const rect = rectFor(CLUSTER)!
            const lowestY = Math.max(...rect.outline.map((point) => point.y))
            const highestY = Math.min(...rect.outline.map((point) => point.y))

            expect(rect.medianY).toBeLessThan(lowestY)
            expect(rect.medianY).toBeGreaterThan(highestY)
        })

        it('draws one marker per observation, inside the slot', () => {
            const rect = rectFor(CLUSTER)!

            expect(rect.points).toHaveLength(CLUSTER.values.length)
            for (const point of rect.points) {
                expect(point.x).toBeGreaterThanOrEqual(rect.x)
                expect(point.x).toBeLessThanOrEqual(rect.x + rect.width)
            }
        })

        it('draws no markers when points are off', () => {
            expect(rectFor(CLUSTER, { showPoints: false })!.points).toEqual([])
        })

        it('caps the markers for a very large group', () => {
            const values = Array.from({ length: 5000 }, (_, i) => (i * 7919) % 1000)

            expect(rectFor({ values })!.points).toHaveLength(500)
        })

        it('is deterministic between calls', () => {
            expect(rectFor(CLUSTER)).toEqual(rectFor(CLUSTER))
        })

        it('draws a bump for identical values', () => {
            const rect = rectFor({ values: [5, 5, 5, 5] })!

            expect(Math.max(...rect.outline.map((point) => point.halfWidth))).toBeGreaterThan(0)
        })

        it.each([
            ['no observations', { values: [] }, 'Mon'],
            ['only non-finite observations', { values: [Number.NaN] }, 'Mon'],
            ['a label outside the band domain', CLUSTER, 'Sun'],
        ])('returns null for %s', (_name, datum, label) => {
            const scales = scalesFor([CLUSTER])

            expect(
                computeViolinRect({
                    seriesKey: 'a',
                    label,
                    dataIndex: 0,
                    datum,
                    scales,
                    grouped: false,
                    showPoints: true,
                })
            ).toBeNull()
        })

        it('estimates the density on a log axis and drops values that cannot be placed on it', () => {
            const datum: ViolinPlotDatum = { values: [-1, 0, 10, 100, 1000] }
            const scales = scalesFor([datum], { scaleType: 'log', range: [10, 1000] })

            const rect = computeViolinRect({
                seriesKey: 'a',
                label: 'Mon',
                dataIndex: 0,
                datum,
                scales,
                grouped: false,
                logScale: true,
                showPoints: true,
            })!

            expect(rect.points).toHaveLength(3)
            expect(rect.outline.every((point) => Number.isFinite(point.y))).toBe(true)
        })
    })

    describe('computeSeriesViolins', () => {
        it('skips null entries and keeps the original index', () => {
            const data = [null, CLUSTER]
            const violins = computeSeriesViolins({
                seriesKey: 'a',
                data,
                labels: LABELS,
                scales: scalesFor(data),
                grouped: false,
                showPoints: false,
            })

            expect(violins.map((violin) => violin.dataIndex)).toEqual([1])
        })
    })
})
