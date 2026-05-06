import { DEFAULT_Y_AXIS_ID } from 'lib/hog-charts'

import { ChartDisplayType } from '~/types'

import { buildMainTrendsSeries, buildTrendsSeries, type TrendsResultLike } from './trendsChartTransforms'

const RED = '#ff0000'

const makeResult = (overrides: Partial<TrendsResultLike> = {}): TrendsResultLike => ({
    id: 0,
    label: 'Pageview',
    data: [1, 2, 3, 4, 5],
    ...overrides,
})

describe('trendsChartTransforms', () => {
    describe('buildMainTrendsSeries', () => {
        it('builds a single main series with no compare and no in-progress tail', () => {
            const series = buildMainTrendsSeries(makeResult(), 0, { getColor: () => RED })

            expect(series).toMatchObject({
                key: '0',
                label: 'Pageview',
                data: [1, 2, 3, 4, 5],
                color: RED,
                yAxisId: DEFAULT_Y_AXIS_ID,
            })
            expect(series.stroke).toBeUndefined()
            expect(series.fill).toBeUndefined()
            expect(series.visibility).toBeUndefined()
        })

        it('keeps compare-previous color un-dimmed (comparisonOf does the dimming downstream)', () => {
            const series = buildMainTrendsSeries(makeResult({ compare: true, compare_label: 'previous' }), 0, {
                getColor: () => RED,
            })

            expect(series.color).toBe(RED)
        })

        it('sets a dashed in-progress tail on active series and skips it on compare-previous', () => {
            const data = [1, 2, 3, 4, 5, 6, 7]
            const opts = { getColor: () => RED, incompletenessOffsetFromEnd: -2 }

            const active = buildMainTrendsSeries(makeResult({ data, compare: true, compare_label: 'current' }), 0, opts)
            const previous = buildMainTrendsSeries(
                makeResult({ data, compare: true, compare_label: 'previous' }),
                1,
                opts
            )

            expect(active.stroke).toEqual({ partial: { fromIndex: 5 } })
            expect(previous.stroke).toBeUndefined()
        })

        it('skips the dashed tail entirely for stickiness', () => {
            const series = buildMainTrendsSeries(makeResult({ data: [1, 2, 3, 4, 5, 6, 7] }), 0, {
                getColor: () => RED,
                incompletenessOffsetFromEnd: -2,
                isStickiness: true,
            })
            expect(series.stroke).toBeUndefined()
        })

        it('attaches an empty fill object for ActionsAreaGraph display', () => {
            const series = buildMainTrendsSeries(makeResult(), 0, {
                getColor: () => RED,
                display: ChartDisplayType.ActionsAreaGraph,
            })
            expect(series.fill).toEqual({})
        })

        it('marks a series excluded when getHidden returns true', () => {
            const series = buildMainTrendsSeries(makeResult(), 0, {
                getColor: () => RED,
                getHidden: () => true,
            })
            expect(series.visibility).toEqual({ excluded: true })
        })

        it('attaches the meta payload returned by buildMeta', () => {
            const meta = { breakdown_value: 'spike', order: 7 }
            const series = buildMainTrendsSeries(makeResult(), 0, {
                getColor: () => RED,
                buildMeta: () => meta,
            })
            expect(series.meta).toBe(meta)
        })

        it('falls back to empty string label when result has none', () => {
            const series = buildMainTrendsSeries(makeResult({ label: null }), 0, { getColor: () => RED })
            expect(series.label).toBe('')
        })

        it('keeps index 0 on the default y-axis even when showMultipleYAxes is true', () => {
            const series = buildMainTrendsSeries(makeResult(), 0, { getColor: () => RED, showMultipleYAxes: true })
            expect(series.yAxisId).toBe(DEFAULT_Y_AXIS_ID)
        })

        it('skips the dashed tail when incompletenessOffsetFromEnd is 0', () => {
            const series = buildMainTrendsSeries(makeResult({ data: [1, 2, 3] }), 0, {
                getColor: () => RED,
                incompletenessOffsetFromEnd: 0,
            })
            expect(series.stroke).toBeUndefined()
        })

        it('passes the result index through to getColor and buildMeta', () => {
            const getColor = jest.fn(() => RED)
            const buildMeta = jest.fn(() => ({}))
            buildMainTrendsSeries(makeResult(), 7, { getColor, buildMeta })
            expect(getColor).toHaveBeenCalledWith(expect.anything(), 7)
            expect(buildMeta).toHaveBeenCalledWith(expect.anything(), 7)
        })
    })

    describe('buildTrendsSeries', () => {
        it('returns one main series per result', () => {
            const results = [makeResult({ id: 'a' }), makeResult({ id: 'b' })]
            const series = buildTrendsSeries(results, { getColor: () => RED })

            expect(series).toHaveLength(2)
            expect(series.map((s) => s.key)).toEqual(['a', 'b'])
        })

        it('assigns yAxisIds [left, y1, y2] across three results when showMultipleYAxes is true', () => {
            const results = [makeResult({ id: 'a' }), makeResult({ id: 'b' }), makeResult({ id: 'c' })]
            const series = buildTrendsSeries(results, { getColor: () => RED, showMultipleYAxes: true })

            expect(series.map((s) => s.yAxisId)).toEqual([DEFAULT_Y_AXIS_ID, 'y1', 'y2'])
        })
    })
})
