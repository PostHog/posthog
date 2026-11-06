import { scaleLinear } from 'd3'

import { createOfflineScoreTrendTickFormatter } from './offlineScoreTrendAxis'

describe('offline score trend axis', () => {
    it.each([
        ['2026-01-08T10:00:00Z', '2026-01-08T11:00:00Z'],
        ['2026-01-08T10:00:00Z', '2026-01-09T10:00:00Z'],
        ['2026-01-08T10:00:00Z', '2026-01-08T10:01:00Z'],
        ['2025-01-01T00:00:00Z', '2027-01-01T00:00:00Z'],
    ])('distinguishes calendar ticks between %s and %s', (start, end) => {
        const domain: [number, number] = [Date.parse(start), Date.parse(end)]
        const formatter = createOfflineScoreTrendTickFormatter(domain, false, 'UTC')
        const labels = scaleLinear().domain(domain).ticks(12).map(formatter)

        expect(labels.length).toBeGreaterThan(1)
        expect(new Set(labels).size).toBe(labels.length)
    })

    it('uses the selected timezone for the year boundary and time of day', () => {
        const domain: [number, number] = [Date.parse('2026-01-01T00:00:00Z'), Date.parse('2026-01-02T00:00:00Z')]
        const formatter = createOfflineScoreTrendTickFormatter(domain, false, 'America/New_York')

        expect(formatter(domain[0])).toBe('Dec 31, 2025 19:00')
        expect(formatter(domain[1])).toBe('Jan 1, 2026 19:00')
    })

    it.each([60000, 3600000, 86400000])('distinguishes elapsed ticks over %i milliseconds', (duration) => {
        const domain: [number, number] = [0, duration]
        const formatter = createOfflineScoreTrendTickFormatter(domain, true, 'UTC')
        const labels = scaleLinear().domain(domain).ticks(12).map(formatter)

        expect(labels.length).toBeGreaterThan(1)
        expect(new Set(labels).size).toBe(labels.length)
        expect(formatter(60000)).toBe('1m')
    })
})
