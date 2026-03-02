import { createXAxisTickCallback } from './formatXAxisTick'

function weeklyDates(start: string, count: number): string[] {
    const dates: string[] = []
    const d = new Date(start + 'T00:00:00Z')
    for (let i = 0; i < count; i++) {
        dates.push(d.toISOString().slice(0, 10))
        d.setDate(d.getDate() + 7)
    }
    return dates
}

function hourlyDates(start: string, count: number): string[] {
    return Array.from({ length: count }, (_, i) => {
        const d = new Date(Date.UTC(+start.slice(0, 4), +start.slice(5, 7) - 1, +start.slice(8, 10), i))
        return d.toISOString().replace('T', ' ').slice(0, 19)
    })
}

function sparseLabels(length: number, labels: Record<number, string>): (string | null)[] {
    return Array.from({ length }, (_, i) => labels[i] ?? null)
}

describe('createXAxisTickCallback', () => {
    describe.each([
        {
            scenario: 'inferred month interval from ~30 day gaps',
            interval: undefined,
            allDays: ['2025-01-01', '2025-02-01', '2025-03-01'],
            expected: ['2025', 'February', 'March'],
        },
        {
            scenario: 'inferred day interval from 1 day gaps',
            interval: undefined,
            allDays: ['2025-04-01', '2025-04-02', '2025-04-03'],
            expected: ['April', 'Apr 2', 'Apr 3'],
        },
        {
            scenario: 'inferred week interval from 7 day gaps',
            interval: undefined,
            allDays: ['2025-04-07', '2025-04-14', '2025-04-21'],
            expected: ['Apr 7', 'Apr 14', 'Apr 21'],
        },
        {
            scenario: 'inferred hour interval from 1 hour gaps',
            interval: undefined,
            allDays: ['2025-04-01 10:00:00', '2025-04-01 11:00:00', '2025-04-01 12:00:00'],
            expected: ['10:00', '11:00', '12:00'],
        },
        {
            scenario: 'inferred minute interval from sub-hour gaps',
            interval: undefined,
            allDays: ['2025-04-01 10:00:00', '2025-04-01 10:01:00', '2025-04-01 10:02:00'],
            expected: ['10:00', '10:01', '10:02'],
        },
        {
            scenario: 'second interval formats as HH:mm',
            interval: 'second' as const,
            allDays: ['2025-04-01 14:30:00', '2025-04-01 14:30:01', '2025-04-01 14:30:02'],
            expected: ['14:30', '14:30', '14:30'],
        },
        {
            scenario: 'monthly, same year starting Jan → year then full month names',
            interval: 'month' as const,
            allDays: ['2025-01-01', '2025-02-01', '2025-03-01', '2025-04-01'],
            expected: ['2025', 'February', 'March', 'April'],
        },
        {
            scenario: 'monthly, same year mid-year → full month names',
            interval: 'month' as const,
            allDays: ['2025-04-01', '2025-05-01', '2025-06-01'],
            expected: ['April', 'May', 'June'],
        },
        {
            scenario: 'monthly, cross year → year at January boundary',
            interval: 'month' as const,
            allDays: ['2025-11-01', '2025-12-01', '2026-01-01', '2026-02-01'],
            expected: ['November', 'December', '2026', 'February'],
        },
        {
            scenario: 'daily, short span → full month name on 1st, MMM D otherwise',
            interval: 'day' as const,
            allDays: ['2025-04-28', '2025-04-29', '2025-04-30', '2025-05-01', '2025-05-02'],
            expected: ['Apr 28', 'Apr 29', 'Apr 30', 'May', 'May 2'],
        },
        {
            scenario: 'daily, short span crossing Jan 1 → year on 1st',
            interval: 'day' as const,
            allDays: ['2025-12-30', '2025-12-31', '2026-01-01', '2026-01-02'],
            expected: ['Dec 30', 'Dec 31', '2026', 'Jan 2'],
        },
        {
            scenario: 'daily, long span (3 weeks) → MMM D with year on Jan 1',
            interval: 'day' as const,
            allDays: ['2025-12-30', '2025-12-31', '2026-01-01', '2026-01-02', '2026-01-03'],
            expected: ['Dec 30', 'Dec 31', '2026', 'Jan 2', 'Jan 3'],
        },
        {
            scenario: 'weekly, short span (2 months), no 1st → all MMM D',
            interval: 'week' as const,
            allDays: ['2025-04-07', '2025-04-14', '2025-04-21', '2025-04-28', '2025-05-05', '2025-05-12'],
            expected: ['Apr 7', 'Apr 14', 'Apr 21', 'Apr 28', 'May 5', 'May 12'],
        },
        {
            scenario: 'weekly, short span with 1st → full month name on 1st',
            interval: 'week' as const,
            allDays: ['2025-09-22', '2025-09-29', '2025-10-06', '2025-10-13', '2025-11-01', '2025-11-08'],
            expected: ['Sep 22', 'Sep 29', 'Oct 6', 'Oct 13', 'November', 'Nov 8'],
        },
        {
            scenario: 'weekly, long span starting mid-month → drops partial first month',
            interval: 'week' as const,
            allDays: weeklyDates('2025-08-24', 26),
            expected: sparseLabels(26, {
                2: 'September',
                6: 'October',
                10: 'November',
                15: 'December',
                19: '2026',
                23: 'February',
            }),
        },
        {
            scenario: 'weekly, long span starting on 1st → keeps first month',
            interval: 'week' as const,
            allDays: weeklyDates('2025-09-01', 18),
            expected: sparseLabels(18, {
                0: 'September',
                5: 'October',
                9: 'November',
                13: 'December',
            }),
        },
        {
            scenario: 'hourly, single day → HH:mm',
            interval: 'hour' as const,
            allDays: ['2025-04-01 14:00:00', '2025-04-01 15:00:00', '2025-04-01 16:00:00'],
            expected: ['14:00', '15:00', '16:00'],
        },
        {
            scenario: 'minute',
            interval: 'minute' as const,
            allDays: ['2025-04-01 14:30:00', '2025-04-01 14:31:00', '2025-04-01 14:32:00'],
            expected: ['14:30', '14:31', '14:32'],
        },
        {
            scenario: 'hourly, multi-day (3 days) → date at midnight, HH:mm every 6h, null otherwise',
            interval: 'hour' as const,
            allDays: hourlyDates('2025-02-15', 72),
            expected: sparseLabels(72, {
                0: 'Feb 15',
                6: '06:00',
                12: '12:00',
                18: '18:00',
                24: 'Feb 16',
                30: '06:00',
                36: '12:00',
                42: '18:00',
                48: 'Feb 17',
                54: '06:00',
                60: '12:00',
                66: '18:00',
            }),
        },
    ])('$scenario', ({ interval, allDays, expected }) => {
        const callback = createXAxisTickCallback({ interval, allDays, timezone: 'UTC' })

        it.each(expected.map((exp, i) => ({ index: i, expected: exp })))(
            'formats index $index as $expected',
            ({ index, expected: exp }) => {
                expect(callback('ignored', index)).toBe(exp)
            }
        )
    })

    describe('non-UTC timezone', () => {
        it('shifts hour labels according to timezone offset', () => {
            const callback = createXAxisTickCallback({
                interval: 'hour',
                allDays: ['2025-04-01 00:00:00', '2025-04-01 01:00:00', '2025-04-01 02:00:00'],
                timezone: 'America/New_York',
            })
            expect(callback('ignored', 0)).toBe('20:00')
            expect(callback('ignored', 1)).toBe('21:00')
            expect(callback('ignored', 2)).toBe('22:00')
        })
    })

    describe('fallbacks', () => {
        it('returns raw value when allDays is empty', () => {
            const callback = createXAxisTickCallback({ interval: 'day', allDays: [], timezone: 'UTC' })
            expect(callback('2025-04-01', 0)).toBe('2025-04-01')
        })

        it('returns raw value when index is out of bounds', () => {
            const callback = createXAxisTickCallback({
                interval: 'day',
                allDays: ['2025-04-01'],
                timezone: 'UTC',
            })
            expect(callback('some-label', 5)).toBe('some-label')
        })

        it('returns raw value for unparseable dates', () => {
            const callback = createXAxisTickCallback({
                interval: 'day',
                allDays: ['not-a-date'],
                timezone: 'UTC',
            })
            expect(callback('fallback', 0)).toBe('fallback')
        })
    })
})
