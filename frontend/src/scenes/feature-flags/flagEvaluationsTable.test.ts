import { dayjs } from 'lib/dayjs'

import { insightReachesPastFlagEvaluationsRetention } from './flagEvaluationsTable'

const daysAgo = (days: number): string => dayjs.utc().subtract(days, 'day').toISOString()
const now = (): string => dayjs.utc().toISOString()

describe('flagEvaluationsTable', () => {
    it.each([
        ['a range inside the window', '-30d', { date_from: daysAgo(30), date_to: now() }, undefined, false],
        ['a range past the window', '-180d', { date_from: daysAgo(180), date_to: now() }, undefined, true],
        [
            'all time, which resolves inside the window',
            'all',
            { date_from: daysAgo(10), date_to: now() },
            undefined,
            true,
        ],
        ['a query that has not run yet', '-180d', undefined, undefined, false],
        [
            'a previous period inside the window',
            '-30d',
            { date_from: daysAgo(30), date_to: now() },
            { compare: true },
            false,
        ],
        [
            'a previous period that doubles the range back past the window',
            '-60d',
            { date_from: daysAgo(60), date_to: now() },
            { compare: true },
            true,
        ],
        [
            'a comparison shifted inside the window',
            '-30d',
            { date_from: daysAgo(30), date_to: now() },
            { compare: true, compare_to: '-30d' },
            false,
        ],
        [
            'a comparison shifted past the window',
            '-30d',
            { date_from: daysAgo(30), date_to: now() },
            { compare: true, compare_to: '-1y' },
            true,
        ],
    ])(
        'insightReachesPastFlagEvaluationsRetention: %s',
        (_name, dateFrom, resolvedDateRange, compareFilter, expected) => {
            expect(insightReachesPastFlagEvaluationsRetention({ dateFrom, resolvedDateRange, compareFilter })).toBe(
                expected
            )
        }
    )
})
