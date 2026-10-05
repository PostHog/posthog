import {
    aggregateOfflineScoreHistory,
    buildOfflineTrendPanels,
    formatOfflineNumericScore,
    formatOfflineScore,
    previousOfflinePeriod,
    resolveOfflineDateRange,
    offlineScoreMetricLabel,
} from './offlineScoreTrends'
import { makeOfflineHistoryPoint } from './offlineScoreTrends.fixtures'

describe('offline score trends', () => {
    it.each([
        ['gte', 0.9999999, 1, '0.9999999'],
        ['lte', 1.0000001, 1, '1.0000001'],
        ['gte', 1.0000001, 1.0000001, '1.0000001'],
        ['lte', -0.9999999, -1, '-0.9999999'],
        ['gte', 1.23456789, 1, '1.23457'],
    ] as const)('keeps the displayed mean consistent with %s for %s at %s', (operator, value, threshold, label) => {
        const point = makeOfflineHistoryPoint(1, value)
        point.summary.scorer.config = { passing_rule: { operator, threshold } }
        expect(formatOfflineScore(point.summary)).toBe(label)
    })

    it.each([
        {
            label: 'unequal weights and unsuccessful experiments',
            samples: [
                { mean: 5, ok: 2 },
                { mean: 0, ok: 8 },
                { mean: null, ok: 0 },
            ],
            expected: 1,
        },
        {
            label: 'the largest finite scores',
            samples: Array.from({ length: 100 }, () => ({ mean: Number.MAX_VALUE, ok: 1 })),
            expected: Number.MAX_VALUE,
        },
        {
            label: 'opposite-sign extreme scores',
            samples: [
                { mean: Number.MAX_VALUE, ok: 1 },
                { mean: -Number.MAX_VALUE, ok: 1 },
            ],
            expected: 0,
        },
        { label: 'all-zero scores', samples: [{ mean: 0, ok: 2 }], expected: 0 },
    ])('weights experiment means with $label', ({ samples, expected }) => {
        const points = samples.map(({ mean, ok }, index) => {
            const point = makeOfflineHistoryPoint(1, mean)
            point.experiment.id = `experiment-${index}`
            point.summary.status_counts.ok = ok
            return point
        })
        const summary = aggregateOfflineScoreHistory(points)!

        expect(summary.experimentCount).toBe(samples.length)
        expect(summary.status_counts.ok).toBe(samples.reduce((total, sample) => total + sample.ok, 0))
        expect(summary.mean).toBe(expected)
        expect(formatOfflineScore(summary)).toBe(formatOfflineNumericScore(expected))
    })

    it('aggregates boolean rates over successful results including false outcomes and excluding errors', () => {
        const points = [makeOfflineHistoryPoint(1), makeOfflineHistoryPoint(2)]
        for (const [index, point] of points.entries()) {
            point.summary.scorer = { ...point.summary.scorer, kind: 'boolean', config: {} }
            point.summary.mean = null
            point.summary.status_counts = { ok: index === 0 ? 2 : 8, error: 5, skipped: 0, not_applicable: 0 }
            point.summary.true_count = index === 0 ? 0 : 6
            point.summary.false_count = 2
            point.summary.true_rate = index === 0 ? 0 : 0.75
            point.summary.pass_count = point.summary.true_count
            point.summary.fail_count = point.summary.false_count
            point.summary.pass_rate = point.summary.true_rate
        }

        const summary = aggregateOfflineScoreHistory(points)!

        expect(summary.true_rate).toBe(0.6)
        expect(summary.pass_rate).toBe(0.6)
        expect(summary.status_counts.ok).toBe(10)
        expect(formatOfflineScore(summary)).toBe('60%')
    })

    it.each([false, true])('plots and aggregates actual boolean pass counts for polarity %s', (trueIsFailure) => {
        const points = [makeOfflineHistoryPoint(1), makeOfflineHistoryPoint(2)]
        for (const [index, point] of points.entries()) {
            point.summary.scorer = {
                ...point.summary.scorer,
                kind: 'boolean',
                config: { true_is_failure: trueIsFailure },
            }
            point.summary.status_counts = { ok: index === 0 ? 2 : 8, error: 5, skipped: 1, not_applicable: 1 }
            point.summary.true_count = index === 0 ? 0 : 6
            point.summary.false_count = 2
            point.summary.true_rate = index === 0 ? 0 : 0.75
            point.summary.pass_count = trueIsFailure ? 2 : point.summary.true_count
            point.summary.fail_count = trueIsFailure ? point.summary.true_count : 2
            point.summary.pass_rate = point.summary.pass_count / point.summary.status_counts.ok
        }
        const summary = aggregateOfflineScoreHistory(points)!
        expect(summary.pass_count).toBe(trueIsFailure ? 4 : 6)
        expect(summary.fail_count).toBe(trueIsFailure ? 6 : 4)
        expect(summary.pass_rate).toBe(trueIsFailure ? 0.4 : 0.6)
        expect(summary.true_rate).toBe(0.6)
        expect(formatOfflineScore(summary)).toBe(trueIsFailure ? '40%' : '60%')
        expect(offlineScoreMetricLabel(summary.scorer)).toBe('Pass rate')
        const [panel] = buildOfflineTrendPanels([{ key: 'current', label: 'Current', points }])
        expect(panel.series[0].points.map((point) => point.y)).toEqual(trueIsFailure ? [1, 0.25] : [0, 0.75])
    })

    it('keeps version thresholds separate and includes off-scale thresholds without treating mean as pass rate', () => {
        const points = [makeOfflineHistoryPoint(1, 4), makeOfflineHistoryPoint(2, 4)]
        for (const [index, point] of points.entries()) {
            point.summary.scorer = {
                ...point.summary.scorer,
                id: `version-${index}`,
                config: { min: 0, max: 5, passing_rule: { operator: index === 0 ? 'gte' : 'lte', threshold: 1 } },
            }
            point.summary.pass_count = 23
            point.summary.fail_count = 69
            point.summary.pass_rate = 0.25
        }
        const panels = buildOfflineTrendPanels([{ key: 'current', label: 'Current', points }])
        expect(panels).toHaveLength(2)
        expect(panels.map((panel) => panel.passingRule?.operator)).toEqual(['gte', 'lte'])
        expect(panels.every((panel) => panel.yDomain![0] < 1 && panel.yDomain![1] > 4)).toBe(true)
        expect(panels.map((panel) => panel.series[0].points[0].y)).toEqual([4, 4])
        const summary = aggregateOfflineScoreHistory([points[0]])!
        expect(formatOfflineScore(summary)).toBe('4')
        expect(summary.pass_rate).toBe(0.25)
    })

    it.each([false, true])('aggregates category counts and passing rules (graded: %s)', (graded) => {
        const points = [makeOfflineHistoryPoint(1), makeOfflineHistoryPoint(2)]
        for (const [index, point] of points.entries()) {
            point.summary.scorer = {
                ...point.summary.scorer,
                kind: 'categorical',
                config: {
                    selection_mode: 'multiple',
                    ...(graded ? { passing_rule: { categories: ['complete'] } } : {}),
                    options: [
                        { key: 'complete', label: 'Complete' },
                        { key: 'clear', label: 'Clear' },
                        { key: 'other', label: 'Other' },
                    ],
                },
            }
            point.summary.mean = null
            point.summary.status_counts.ok = index === 0 ? 2 : 8
            point.summary.categories = [
                { key: 'complete', label: 'Complete', count: index === 0 ? 2 : 8, rate: 1 },
                { key: 'clear', label: 'Clear', count: index === 0 ? 2 : 4, rate: index === 0 ? 1 : 0.5 },
                { key: 'other', label: 'Other', count: 0, rate: 0 },
            ]
        }
        if (graded) {
            points[0].summary.pass_count = 0
            points[0].summary.fail_count = 2
            points[1].summary.pass_count = 4
            points[1].summary.fail_count = 4
        }
        points[1].summary.categories.reverse()

        const summary = aggregateOfflineScoreHistory(points)!

        expect([summary.pass_count, summary.fail_count, summary.pass_rate]).toEqual(
            graded ? [4, 6, 0.4] : [null, null, null]
        )
        expect(summary.categories).toEqual([
            { key: 'complete', label: 'Complete', count: 10, rate: 1 },
            { key: 'clear', label: 'Clear', count: 6, rate: 0.6 },
            { key: 'other', label: 'Other', count: 0, rate: 0 },
        ])
        expect(formatOfflineScore(summary)).toBe('Complete: 100%, Clear: 60%, Other: 0%')
    })

    it.each([
        { label: 'empty', points: [] },
        { label: 'unsuccessful', points: [makeOfflineHistoryPoint(1, null)] },
    ])('handles an $label selection without successful scores', ({ points }) => {
        const summary = aggregateOfflineScoreHistory(points)

        if (points.length === 0) {
            expect(summary).toBeNull()
        } else {
            expect(summary).toMatchObject({ experimentCount: 1, status_counts: { ok: 0 }, mean: null, true_rate: null })
            expect(formatOfflineScore(summary!)).toBe('No successful results')
        }
    })

    it.each(['boolean', 'categorical'] as const)(
        'plots %s rates without treating false as missing or normalizing multiple selections',
        (kind) => {
            const point = makeOfflineHistoryPoint(1)
            point.summary.scorer = {
                ...point.summary.scorer,
                kind,
                config:
                    kind === 'boolean'
                        ? { true_label: 'Relevant', false_label: 'Unrelated' }
                        : {
                              options: [
                                  { key: 'clear', label: 'Clear' },
                                  { key: 'complete', label: 'Complete' },
                              ],
                              selection_mode: 'multiple',
                          },
            }
            point.summary.mean = null
            point.summary.true_rate = 0
            point.summary.pass_count = kind === 'boolean' ? 0 : null
            point.summary.fail_count = kind === 'boolean' ? point.summary.status_counts.ok : null
            point.summary.pass_rate = kind === 'boolean' ? 0 : null
            point.summary.categories = [
                { key: 'clear', label: 'Clear', count: 69, rate: 0.75 },
                { key: 'complete', label: 'Complete', count: 69, rate: 0.75 },
            ]
            const [panel] = buildOfflineTrendPanels([{ key: 'a', label: 'A', points: [point] }])
            expect(panel.series.map((series) => series.points[0].y)).toEqual(kind === 'boolean' ? [0] : [0.75, 0.75])
            expect(panel.yDomain).toEqual([0, 1])
        }
    )

    it('preserves repeated execution timestamps, zero scores, and exact version identity without plotting missing scores', () => {
        const first = makeOfflineHistoryPoint(1, 0)
        const second = makeOfflineHistoryPoint(2, 4)
        second.experiment.started_at = first.experiment.started_at
        second.summary.scorer = { ...second.summary.scorer, id: 'other-version', version: 3 }
        const panels = buildOfflineTrendPanels([
            { key: 'primary', label: 'Selected', points: [first, second, makeOfflineHistoryPoint(3, null)] },
        ])
        expect(panels).toHaveLength(1)
        const timestamp = Date.parse(first.experiment.started_at)
        expect(panels[0].xDomain).toEqual([timestamp - 43200000, timestamp + 43200000])
        expect(panels[0].series.map(({ points }) => points.map(({ x, y }) => [x, y]))).toEqual([
            [[Date.parse(first.experiment.started_at), 0]],
            [[Date.parse(first.experiment.started_at), 4]],
        ])
        expect(formatOfflineScore(first.summary)).toBe('0')
        expect(formatOfflineNumericScore(0.000000123)).not.toBe('0')
    })

    it('keeps numeric configurations apart and uses common y domains for unequal periods', () => {
        const first = makeOfflineHistoryPoint(1, 2)
        const second = makeOfflineHistoryPoint(2, 4)
        const third = makeOfflineHistoryPoint(3, 80)
        third.summary.scorer = { ...third.summary.scorer, id: 'percentage-version', config: { min: 0, max: 100 } }
        const panels = buildOfflineTrendPanels([
            { key: 'primary', label: 'Selected', points: [first, third], dateFrom: '2026-01-01', dateTo: '2026-01-11' },
            { key: 'comparison', label: 'Comparison', points: [second], dateFrom: '2026-01-01', dateTo: '2026-01-06' },
        ])
        expect(panels).toHaveLength(3)
        expect(panels.every((panel) => !panel.elapsed)).toBe(true)
        expect(panels[0].yDomain).toEqual(panels[2].yDomain)
        expect(panels[0].series[0].points[0].x).toBe(Date.parse(first.experiment.started_at))
    })

    it('aligns equal windows by elapsed time without changing the actual execution date', () => {
        const point = makeOfflineHistoryPoint(2)
        const panels = buildOfflineTrendPanels([
            { key: 'a', label: 'A', points: [point], dateFrom: '2026-01-01T00:00:00Z', dateTo: '2026-01-08T00:00:00Z' },
            { key: 'b', label: 'B', points: [point], dateFrom: '2026-01-01T00:00:00Z', dateTo: '2026-01-08T00:00:00Z' },
        ])
        expect(panels).toHaveLength(1)
        expect(panels[0].elapsed).toBe(true)
        expect(panels[0].xDomain).toEqual([0, 7 * 86400000])
        expect(panels[0].series[0].points[0].x).toBe(34 * 3600000)
        expect(panels[0].series[0].points[0].meta?.point.experiment.started_at).toBe(point.experiment.started_at)
    })

    it('resolves a fixed date end to exclusive local midnight across daylight saving time', () => {
        expect(resolveOfflineDateRange('2026-03-08', '2026-03-08', '2026-03-09T12:00:00Z', 'America/New_York')).toEqual(
            { dateFrom: '2026-03-08T05:00:00.000Z', dateTo: '2026-03-09T04:00:00.000Z' }
        )
    })

    it('uses one frozen reference time for rolling periods and rejects undefined previous all-time periods', () => {
        const range = resolveOfflineDateRange('-24h', null, '2026-01-20T12:34:56Z', 'UTC')
        expect(range).toEqual({ dateFrom: '2026-01-19T12:34:56.000Z', dateTo: '2026-01-20T12:34:56.000Z' })
        expect(previousOfflinePeriod(range)).toEqual({
            dateFrom: '2026-01-18T12:34:56.000Z',
            dateTo: '2026-01-19T12:34:56.000Z',
        })
        expect(previousOfflinePeriod(resolveOfflineDateRange('all', null))).toBeNull()
    })
})
