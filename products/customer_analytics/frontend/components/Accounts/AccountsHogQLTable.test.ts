import { buildHistoryDisplay } from './AccountsHogQLTable'

const DAY = 24 * 60 * 60
const NOW_MS = 1_800_000_000_000
const NOW_S = NOW_MS / 1000

const daysAgo = (days: number): number => Math.floor(NOW_S - days * DAY)

describe('buildHistoryDisplay', () => {
    it('carries the last pre-window write forward so sparse histories still chart', () => {
        const points: [number, number][] = [
            [daysAgo(45), 100],
            [daysAgo(3), 120],
        ]
        const { latest, baseline, chartPoints } = buildHistoryDisplay(points, 7, NOW_MS)
        expect(latest).toEqual([daysAgo(3), 120])
        expect(baseline).toEqual([daysAgo(7), 100])
        expect(chartPoints).toEqual([
            [daysAgo(7), 100],
            [daysAgo(3), 120],
        ])
    })

    it('uses only in-window points when nothing precedes the window', () => {
        const points: [number, number][] = [
            [daysAgo(5), 10],
            [daysAgo(1), 30],
        ]
        const { baseline, chartPoints } = buildHistoryDisplay(points, 7, NOW_MS)
        expect(baseline).toEqual([daysAgo(5), 10])
        expect(chartPoints).toHaveLength(2)
    })

    it('falls back to a single carried point for a property with one write ever', () => {
        const points: [number, number][] = [[daysAgo(60), 500]]
        const { latest, chartPoints } = buildHistoryDisplay(points, 7, NOW_MS)
        expect(latest).toEqual([daysAgo(60), 500])
        expect(chartPoints).toHaveLength(1)
    })

    it('returns empty state for no history', () => {
        expect(buildHistoryDisplay([], 7, NOW_MS)).toEqual({ latest: null, baseline: null, chartPoints: [] })
    })
})
