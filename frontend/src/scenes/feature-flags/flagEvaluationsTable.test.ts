import { dayjs } from 'lib/dayjs'

import { insightReachesPastFlagEvaluationsRetention } from './flagEvaluationsTable'

// The UTC date is a day ahead of the local date at UTC-12, and equal to it at UTC+14.
const NOW = dayjs.utc('2026-01-31T08:00:00Z')
const daysAgo = (days: number): string => NOW.subtract(days, 'day').toISOString()
const now = (): string => NOW.toISOString()

describe('flagEvaluationsTable', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(NOW.toDate())
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each([
        ['a range inside the window', '-30d', 'UTC', { date_from: daysAgo(30), date_to: now() }, undefined, false],
        ['a range past the window', '-180d', 'UTC', { date_from: daysAgo(180), date_to: now() }, undefined, true],
        [
            'all time, which resolves inside the window',
            'all',
            'UTC',
            { date_from: daysAgo(10), date_to: now() },
            undefined,
            true,
        ],
        ['a query that has not run yet', '-180d', 'UTC', undefined, undefined, false],
        [
            'the 90-day preset two hours ahead of UTC',
            '-90d',
            'Africa/Johannesburg',
            { date_from: '2025-11-02T00:00:00+02:00', date_to: now() },
            undefined,
            false,
        ],
        [
            'the 90-day preset at UTC+14',
            '-90d',
            'Pacific/Kiritimati',
            { date_from: '2025-11-02T00:00:00+14:00', date_to: now() },
            undefined,
            false,
        ],
        [
            'the 90-day preset at UTC-12',
            '-90d',
            'Etc/GMT+12',
            { date_from: '2025-11-01T00:00:00-12:00', date_to: now() },
            undefined,
            false,
        ],
        [
            'the 90-day preset across a daylight saving change that repeats midnight',
            '-90d',
            'America/Havana',
            { date_from: '2025-11-02T00:00:00-04:00', date_to: now() },
            undefined,
            false,
        ],
        [
            'a range that starts an hour before the team-local window',
            '2025-11-01T23:00:00',
            'Pacific/Kiritimati',
            { date_from: '2025-11-01T23:00:00+14:00', date_to: now() },
            undefined,
            true,
        ],
        [
            'a previous period inside the window',
            '-30d',
            'UTC',
            { date_from: daysAgo(30), date_to: now() },
            { compare: true },
            false,
        ],
        [
            'a previous period that doubles the range back past the window',
            '-60d',
            'UTC',
            { date_from: daysAgo(60), date_to: now() },
            { compare: true },
            true,
        ],
        [
            'a comparison shifted inside the window',
            '-30d',
            'UTC',
            { date_from: daysAgo(30), date_to: now() },
            { compare: true, compare_to: '-30d' },
            false,
        ],
        [
            'a comparison shifted past the window',
            '-30d',
            'UTC',
            { date_from: daysAgo(30), date_to: now() },
            { compare: true, compare_to: '-1y' },
            true,
        ],
    ])(
        'insightReachesPastFlagEvaluationsRetention: %s',
        (_name, dateFrom, timezone, resolvedDateRange, compareFilter, expected) => {
            expect(
                insightReachesPastFlagEvaluationsRetention({ dateFrom, timezone, resolvedDateRange, compareFilter })
            ).toBe(expected)
        }
    )
})
