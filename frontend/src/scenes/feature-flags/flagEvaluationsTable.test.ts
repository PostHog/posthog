import { dayjs } from 'lib/dayjs'

import { FlagCallsInsightResponse, flagCallsRetentionGap } from './flagEvaluationsTable'

// The UTC date is a day ahead of the local date at UTC-12, and equal to it at UTC+14. Ninety days back is
// November 2, 2025, when Havana repeats midnight.
const NOW = dayjs.utc('2026-01-31T08:00:00Z')
const daysAgo = (days: number): string => NOW.subtract(days, 'day').toISOString()
const now = (): string => NOW.toISOString()
const resolved = (dateFrom: string, response: FlagCallsInsightResponse = {}): FlagCallsInsightResponse => ({
    resolved_date_range: { date_from: dateFrom, date_to: now() },
    ...response,
})

describe('flagEvaluationsTable', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(NOW.toDate())
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each([
        ['a range inside the window', '-30d', resolved(daysAgo(30)), undefined, null],
        ['a range past the window', '-180d', resolved(daysAgo(180)), undefined, 'periods'],
        ['all time, which resolves inside the window', 'all', resolved(daysAgo(10)), undefined, 'periods'],
        ['a query that has not run yet', '-180d', undefined, undefined, null],
        [
            'the 90-day preset two hours ahead of UTC',
            '-90d',
            resolved('2025-11-02T00:00:00+02:00', { timezone: 'Africa/Johannesburg' }),
            undefined,
            null,
        ],
        [
            'the 90-day preset at UTC+14',
            '-90d',
            resolved('2025-11-02T00:00:00+14:00', { timezone: 'Pacific/Kiritimati' }),
            undefined,
            null,
        ],
        [
            'the 90-day preset at UTC-12',
            '-90d',
            resolved('2025-11-01T00:00:00-12:00', { timezone: 'Etc/GMT+12' }),
            undefined,
            null,
        ],
        [
            'the 90-day preset across a daylight saving change that repeats midnight',
            '-90d',
            resolved('2025-11-02T00:00:00-04:00', { timezone: 'America/Havana' }),
            undefined,
            null,
        ],
        [
            'the 90-day preset in a result cached before team-local midnight',
            '-90d',
            resolved('2025-11-01T00:00:00+02:00', {
                timezone: 'Africa/Johannesburg',
                last_refresh: '2026-01-30T21:00:00Z',
            }),
            undefined,
            null,
        ],
        [
            'a range that starts an hour before the team-local window',
            '2025-11-01T23:00:00',
            resolved('2025-11-01T23:00:00+14:00', { timezone: 'Pacific/Kiritimati' }),
            undefined,
            'periods',
        ],
        [
            'a timezone the browser does not know',
            '-30d',
            resolved(daysAgo(30), { timezone: 'Mars/Olympus_Mons' }),
            undefined,
            null,
        ],
        ['a previous period inside the window', '-30d', resolved(daysAgo(30)), { compare: true }, null],
        [
            'a previous period that doubles the range back past the window',
            '-60d',
            resolved(daysAgo(60)),
            { compare: true },
            'periods',
        ],
        [
            'a comparison shifted inside the window',
            '-30d',
            resolved(daysAgo(30)),
            { compare: true, compare_to: '-30d' },
            null,
        ],
        [
            'a comparison shifted past the window',
            '-30d',
            resolved(daysAgo(30)),
            { compare: true, compare_to: '-1y' },
            'periods',
        ],
        [
            'a Metric whose change pill compares against the period before the 90-day preset',
            '-90d',
            resolved('2025-11-02T00:00:00+02:00', {
                timezone: 'Africa/Johannesburg',
                resolved_compare_date_range: {
                    date_from: '2025-08-03T00:00:00+02:00',
                    date_to: '2025-11-02T00:00:00+02:00',
                },
            }),
            undefined,
            'periods',
        ],
        [
            'a comparison whose start the backend resolved inside the window',
            '-30d',
            resolved(daysAgo(30), { resolved_compare_date_range: { date_from: daysAgo(60), date_to: daysAgo(30) } }),
            { compare: true, compare_to: '-1y' },
            null,
        ],
        [
            'a lifecycle that reads the interval before its range from past the window',
            '-60d',
            { resolved_date_range: { date_from: daysAgo(60), date_to: now(), read_from: daysAgo(120) } },
            undefined,
            'first-period',
        ],
        [
            'a query that reads before its range from inside the window',
            '-30d',
            { resolved_date_range: { date_from: daysAgo(30), date_to: now(), read_from: daysAgo(60) } },
            undefined,
            null,
        ],
        [
            'a range past the window that also reads before it',
            '-100d',
            { resolved_date_range: { date_from: daysAgo(100), date_to: now(), read_from: daysAgo(130) } },
            undefined,
            'periods',
        ],
    ])('flagCallsRetentionGap: %s', (_name, dateFrom, response, compareFilter, expected) => {
        expect(flagCallsRetentionGap({ dateFrom, response, compareFilter })).toBe(expected)
    })
})
