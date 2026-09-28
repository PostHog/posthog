import {
    buildOfflineTrendPanels,
    formatOfflineNumericScore,
    formatOfflineScore,
    previousOfflinePeriod,
    resolveOfflineDateRange,
} from './offlineScoreTrends'
import { makeOfflineHistoryPoint } from './offlineScoreTrends.fixtures'

describe('offline score trends', () => {
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
