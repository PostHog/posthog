import { hexToRGBA } from 'lib/utils'

import { buildTrendsBarTimeSeries, type TrendsBarResultLike } from './trendsBarChartTransforms'

const RED = '#ff0000'

const makeResult = (overrides: Partial<TrendsBarResultLike> = {}): TrendsBarResultLike => ({
    id: 0,
    label: 'Pageview',
    data: [1, 2, 3, 4, 5],
    ...overrides,
})

describe('buildTrendsBarTimeSeries', () => {
    it('returns one series per result with the result data unchanged', () => {
        const results = [makeResult({ id: 'a', data: [1, 2, 3] }), makeResult({ id: 'b', data: [4, 5, 6] })]
        const series = buildTrendsBarTimeSeries(results, { getColor: () => RED })

        expect(series).toHaveLength(2)
        expect(series.map((s) => s.key)).toEqual(['a', 'b'])
        expect(series[0].data).toEqual([1, 2, 3])
        expect(series[1].data).toEqual([4, 5, 6])
    })

    it.each([
        { compare_label: undefined, expectedColor: RED },
        { compare_label: 'previous' as const, expectedColor: hexToRGBA(RED, 0.5) },
    ])(
        'applies getColor and dims compare-previous to 0.5 alpha (compare_label=$compare_label)',
        ({ compare_label, expectedColor }) => {
            const series = buildTrendsBarTimeSeries([makeResult({ compare_label })], { getColor: () => RED })
            expect(series[0].color).toBe(expectedColor)
        }
    )

    it('marks a series excluded when getHidden returns true', () => {
        const series = buildTrendsBarTimeSeries([makeResult()], {
            getColor: () => RED,
            getHidden: () => true,
        })
        expect(series[0].visibility).toEqual({ excluded: true })
    })

    it('attaches the meta payload returned by buildMeta', () => {
        const meta = { breakdown_value: 'spike', order: 7 }
        const series = buildTrendsBarTimeSeries([makeResult()], {
            getColor: () => RED,
            buildMeta: () => meta,
        })
        expect(series[0].meta).toBe(meta)
    })

    it('falls back to empty string label when result label is null', () => {
        const series = buildTrendsBarTimeSeries([makeResult({ label: null })], { getColor: () => RED })
        expect(series[0].label).toBe('')
    })
})
