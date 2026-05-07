import { DEFAULT_Y_AXIS_ID } from 'lib/hog-charts'

import { ChartDisplayType } from '~/types'

import {
    buildDerivedConfigs,
    buildMainTrendsSeries,
    buildTrendsSeries,
    computeDashedFromIndex,
    type TrendsResultLike,
} from './trendsChartTransforms'

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

    describe('computeDashedFromIndex', () => {
        it.each([
            ['active series + negative offset', { compare_label: 'current' }, { incompletenessOffsetFromEnd: -2 }, 5],
            ['plain non-compare series', {}, { incompletenessOffsetFromEnd: -1 }, 6],
        ] as const)('%s → %s', (_, resultOverrides, opts, expected) => {
            const r = makeResult({ data: [1, 2, 3, 4, 5, 6, 7], compare: true, ...resultOverrides })
            expect(computeDashedFromIndex(r, opts)).toBe(expected)
        })

        it.each([
            ['compare-previous', { compare: true, compare_label: 'previous' }, { incompletenessOffsetFromEnd: -2 }],
            ['stickiness', {}, { isStickiness: true, incompletenessOffsetFromEnd: -2 }],
            ['no offset', {}, {}],
            ['offset of 0', {}, { incompletenessOffsetFromEnd: 0 }],
            ['positive offset', {}, { incompletenessOffsetFromEnd: 1 }],
        ] as const)('returns undefined for %s', (_, resultOverrides, opts) => {
            const r = makeResult({ data: [1, 2, 3, 4, 5, 6, 7], ...resultOverrides })
            expect(computeDashedFromIndex(r, opts)).toBeUndefined()
        })
    })

    describe('buildDerivedConfigs', () => {
        it('returns an empty object for empty results', () => {
            expect(buildDerivedConfigs([], { showConfidenceIntervals: true })).toEqual({})
        })

        it('returns an empty object when no derived flags are set', () => {
            expect(buildDerivedConfigs([makeResult()], {})).toEqual({})
        })

        describe('confidenceIntervals', () => {
            it('emits one CI config per result with seriesKey and lower/upper arrays', () => {
                const out = buildDerivedConfigs([makeResult({ id: 'a' }), makeResult({ id: 'b' })], {
                    showConfidenceIntervals: true,
                    confidenceLevel: 95,
                })
                expect(out.confidenceIntervals).toHaveLength(2)
                expect(out.confidenceIntervals?.[0].seriesKey).toBe('a')
                expect(out.confidenceIntervals?.[0].lower).toHaveLength(5)
                expect(out.confidenceIntervals?.[0].upper).toHaveLength(5)
            })

            it('defaults confidenceLevel to 95 when undefined', () => {
                const explicit = buildDerivedConfigs([makeResult()], {
                    showConfidenceIntervals: true,
                    confidenceLevel: 95,
                })
                const defaulted = buildDerivedConfigs([makeResult()], { showConfidenceIntervals: true })
                expect(defaulted.confidenceIntervals?.[0].lower).toEqual(explicit.confidenceIntervals?.[0].lower)
            })

            it('omits confidenceIntervals when showConfidenceIntervals is false', () => {
                expect(buildDerivedConfigs([makeResult()], {}).confidenceIntervals).toBeUndefined()
            })
        })

        describe('movingAverage', () => {
            it('emits MA configs only for results whose data is at least window-long', () => {
                const out = buildDerivedConfigs(
                    [makeResult({ id: 'a', data: [1, 2, 3, 4, 5] }), makeResult({ id: 'b', data: [1, 2] })],
                    { showMovingAverage: true, movingAverageIntervals: 3 }
                )
                expect(out.movingAverage).toEqual([{ seriesKey: 'a', window: 3 }])
            })

            it('omits movingAverage when movingAverageIntervals is undefined', () => {
                expect(buildDerivedConfigs([makeResult()], { showMovingAverage: true }).movingAverage).toBeUndefined()
            })

            it('omits movingAverage when showMovingAverage is false', () => {
                expect(buildDerivedConfigs([makeResult()], { movingAverageIntervals: 3 }).movingAverage).toBeUndefined()
            })
        })

        describe('trendLines', () => {
            it('emits one trendline per visible result with linear kind', () => {
                const out = buildDerivedConfigs([makeResult({ id: 'a' }), makeResult({ id: 'b' })], {
                    showTrendLines: true,
                })
                expect(out.trendLines?.map((t) => t.seriesKey)).toEqual(['a', 'b'])
                expect(out.trendLines?.every((t) => t.kind === 'linear')).toBe(true)
            })

            it('skips hidden results', () => {
                const out = buildDerivedConfigs([makeResult({ id: 'a' }), makeResult({ id: 'b' })], {
                    showTrendLines: true,
                    getHidden: (r) => r.id === 'b',
                })
                expect(out.trendLines?.map((t) => t.seriesKey)).toEqual(['a'])
            })

            it('threads fitUpTo from incompletenessOffsetFromEnd for active series', () => {
                const out = buildDerivedConfigs([makeResult({ data: [1, 2, 3, 4, 5, 6, 7] })], {
                    showTrendLines: true,
                    incompletenessOffsetFromEnd: -2,
                })
                expect(out.trendLines?.[0].fitUpTo).toBe(5)
            })

            it('omits fitUpTo for compare-previous results', () => {
                const out = buildDerivedConfigs(
                    [
                        makeResult({
                            id: 'p',
                            compare: true,
                            compare_label: 'previous',
                            data: [1, 2, 3, 4, 5, 6, 7],
                        }),
                    ],
                    { showTrendLines: true, incompletenessOffsetFromEnd: -2 }
                )
                expect(out.trendLines?.[0].fitUpTo).toBeUndefined()
            })

            it('emits an MA-trendline alongside the raw trendline when MA is also on and data is long enough', () => {
                const out = buildDerivedConfigs([makeResult({ id: 'a', data: [1, 2, 3, 4, 5] })], {
                    showTrendLines: true,
                    showMovingAverage: true,
                    movingAverageIntervals: 3,
                })
                expect(out.trendLines?.map((t) => t.seriesKey)).toEqual(['a', 'a-ma'])
            })

            it('skips the MA-trendline when MA data is gated out by short input', () => {
                const out = buildDerivedConfigs([makeResult({ data: [1, 2] })], {
                    showTrendLines: true,
                    showMovingAverage: true,
                    movingAverageIntervals: 3,
                })
                expect(out.trendLines?.map((t) => t.seriesKey)).toEqual(['0'])
            })

            it('omits trendLines when showTrendLines is false', () => {
                expect(buildDerivedConfigs([makeResult()], {}).trendLines).toBeUndefined()
            })
        })

        describe('comparisonOf', () => {
            it('omits comparisonOf when there are no compare-previous results', () => {
                const out = buildDerivedConfigs([makeResult()], {})
                expect(out.comparisonOf).toBeUndefined()
            })

            it('maps each compare-previous result key to itself (presence-only marker)', () => {
                const out = buildDerivedConfigs(
                    [
                        makeResult({ id: 0, compare: true, compare_label: 'current' }),
                        makeResult({ id: 1, compare: true, compare_label: 'previous' }),
                    ],
                    {}
                )
                expect(out.comparisonOf).toEqual({ '1': '1' })
            })

            it('also marks the MA-of-previous key when MA is enabled', () => {
                const out = buildDerivedConfigs([makeResult({ id: 1, compare: true, compare_label: 'previous' })], {
                    showMovingAverage: true,
                    movingAverageIntervals: 3,
                })
                expect(out.comparisonOf).toEqual({ '1': '1', '1-ma': '1' })
            })

            it('omits the MA-of-previous key when the result is too short for an MA series', () => {
                const out = buildDerivedConfigs(
                    [makeResult({ id: 1, compare: true, compare_label: 'previous', data: [1, 2] })],
                    { showMovingAverage: true, movingAverageIntervals: 3 }
                )
                expect(out.comparisonOf).toEqual({ '1': '1' })
            })
        })
    })
})
