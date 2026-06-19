import tk from 'timekeeper'

import { dayjs } from 'lib/dayjs'
import {
    alignResolvedDateRangeToInterval,
    formatDateTimeRange,
    formatLocalizedDate,
    getConstrainedWeekRange,
    getFormattedLastWeekDate,
    parseDateInTimezone,
} from 'lib/utils/datetime'

describe('datetime utils', () => {
    describe('getFormattedLastWeekDate()', () => {
        it('happy case', () => {
            tk.freeze(new Date(1330688329321))
            expect(getFormattedLastWeekDate()).toEqual('January 13 - March 2, 2012')
            tk.reset()
        })
    })

    describe('formatDateTimeRange()', () => {
        beforeEach(() => {
            tk.freeze(new Date('2025-03-15T12:00:00.000Z'))
        })
        afterEach(() => {
            tk.reset()
        })

        it('formats range in different years with full details', () => {
            const from = dayjs('2024-12-31T14:30:45')
            const to = dayjs('2025-01-01T16:45:30')
            expect(formatDateTimeRange(from, to)).toEqual('December 31, 2024 14:30:45 - January 1, 2025 16:45:30')
        })

        it('formats range in same year but different days', () => {
            const from = dayjs('2024-06-15T09:00:00')
            const to = dayjs('2024-06-20T17:30:00')
            expect(formatDateTimeRange(from, to)).toEqual('June 15, 2024 09:00 - June 20, 17:30')
        })

        it('hides time if both times are midnight', () => {
            const from = dayjs('2024-06-15T00:00:00')
            const to = dayjs('2024-06-20T00:00:00')
            expect(formatDateTimeRange(from, to)).toEqual('June 15, 2024  - June 20')
        })

        it('formats range in same year as current year', () => {
            const from = dayjs('2025-01-10T10:15:00')
            const to = dayjs('2025-02-05T14:20:00')
            expect(formatDateTimeRange(from, to)).toEqual('January 10, 10:15 - February 5, 14:20')
        })

        it('formats range on same day in different year', () => {
            const from = dayjs('2024-08-10T09:30:00')
            const to = dayjs('2024-08-10T18:45:00')
            expect(formatDateTimeRange(from, to)).toEqual('August 10, 2024 09:30 - 18:45')
        })

        it('formats range on same day in current year', () => {
            const from = dayjs('2025-03-15T08:00:00')
            const to = dayjs('2025-03-15T20:00:00')
            expect(formatDateTimeRange(from, to)).toEqual('08:00 - 20:00')
        })

        it('removes seconds when both times have zero seconds on same day', () => {
            const from = dayjs('2025-03-15T10:30:00')
            const to = dayjs('2025-03-15T14:45:00')
            expect(formatDateTimeRange(from, to)).toEqual('10:30 - 14:45')
        })

        it('includes seconds when start time has non-zero seconds', () => {
            const from = dayjs('2025-03-15T10:30:15')
            const to = dayjs('2025-03-15T14:45:00')
            expect(formatDateTimeRange(from, to)).toEqual('10:30:15 - 14:45:00')
        })

        it('includes seconds when end time has non-zero seconds', () => {
            const from = dayjs('2025-03-15T10:30:00')
            const to = dayjs('2025-03-15T14:45:30')
            expect(formatDateTimeRange(from, to)).toEqual('10:30:00 - 14:45:30')
        })

        it('includes seconds when both times have non-zero seconds', () => {
            const from = dayjs('2025-03-15T10:30:15')
            const to = dayjs('2025-03-15T14:45:30')
            expect(formatDateTimeRange(from, to)).toEqual('10:30:15 - 14:45:30')
        })

        it('handles range spanning different days in current year', () => {
            const from = dayjs('2025-03-14T22:00:00')
            const to = dayjs('2025-03-16T02:00:00')
            expect(formatDateTimeRange(from, to)).toEqual('March 14, 22:00 - March 16, 02:00')
        })

        it('handles very short time ranges on same day', () => {
            const from = dayjs('2025-03-15T12:00:00')
            const to = dayjs('2025-03-15T12:01:00')
            expect(formatDateTimeRange(from, to)).toEqual('12:00 - 12:01')
        })
    })

    describe('getConstrainedWeekRange', () => {
        beforeEach(() => {
            // Reset locale to default before each test
            dayjs.updateLocale('en', {
                weekStart: 0,
            })
        })

        describe('basic functionality', () => {
            it('should return week boundaries for a mid-week date with Sunday start', () => {
                const referenceDate = dayjs('2024-01-10') // Wednesday
                const result = getConstrainedWeekRange(referenceDate)

                expect(result.start.format('YYYY-MM-DD')).toBe('2024-01-07') // Sunday
                expect(result.end.format('YYYY-MM-DD')).toBe('2024-01-13') // Saturday
            })

            it('should return week boundaries for a mid-week date with Monday start', () => {
                const referenceDate = dayjs('2024-01-10') // Wednesday
                const result = getConstrainedWeekRange(referenceDate, null, 1)

                expect(result.start.format('YYYY-MM-DD')).toBe('2024-01-08') // Monday
                expect(result.end.format('YYYY-MM-DD')).toBe('2024-01-14') // Sunday
            })

            it('should handle reference date at start of week', () => {
                const referenceDate = dayjs('2024-01-07') // Sunday
                const result = getConstrainedWeekRange(referenceDate, null, 0)

                expect(result.start.format('YYYY-MM-DD')).toBe('2024-01-07') // Sunday
                expect(result.end.format('YYYY-MM-DD')).toBe('2024-01-13') // Saturday
            })

            it('should handle reference date at end of week', () => {
                const referenceDate = dayjs('2024-01-13') // Saturday
                const result = getConstrainedWeekRange(referenceDate, null, 0)

                expect(result.start.format('YYYY-MM-DD')).toBe('2024-01-07') // Sunday
                expect(result.end.format('YYYY-MM-DD')).toBe('2024-01-13') // Saturday
            })
        })

        describe('edge case handling', () => {
            it('should handle Sunday reference date with Monday week start', () => {
                const referenceDate = dayjs('2024-01-07') // Sunday
                const result = getConstrainedWeekRange(referenceDate, null, 1)

                // Sunday should be adjusted to Monday when week starts on Monday
                expect(result.start.format('YYYY-MM-DD')).toBe('2024-01-08') // Monday
                expect(result.end.format('YYYY-MM-DD')).toBe('2024-01-14') // Sunday
            })

            it('should handle Monday reference date with Sunday week start', () => {
                const referenceDate = dayjs('2024-01-08') // Monday
                const result = getConstrainedWeekRange(referenceDate, null, 0)

                // Monday should be adjusted to Sunday when week starts on Sunday
                expect(result.start.format('YYYY-MM-DD')).toBe('2024-01-07') // Sunday
                expect(result.end.format('YYYY-MM-DD')).toBe('2024-01-13') // Saturday
            })

            it('should prevent weekEnd from being before weekStart', () => {
                // This test simulates the edge case where dayjs locale manipulation
                // could cause weekEnd to be calculated before weekStart
                const referenceDate = dayjs('2024-01-01') // Monday, New Year's Day
                const result = getConstrainedWeekRange(referenceDate, null, 1)

                expect(result.start.isSameOrBefore(result.end)).toBe(true)
            })

            it('should handle year boundary dates', () => {
                const referenceDate = dayjs('2023-12-31') // Sunday, New Year's Eve
                const result = getConstrainedWeekRange(referenceDate, null, 0)

                expect(result.start.format('YYYY-MM-DD')).toBe('2023-12-31') // Sunday
                expect(result.end.format('YYYY-MM-DD')).toBe('2024-01-06') // Saturday
            })
        })

        describe('date range boundary constraints', () => {
            it('should constrain start date when boundary start is within week', () => {
                const referenceDate = dayjs('2024-01-10') // Wednesday
                const dateRangeBoundary = {
                    start: dayjs('2024-01-09'), // Tuesday
                    end: dayjs('2024-01-20'),
                }
                const result = getConstrainedWeekRange(referenceDate, dateRangeBoundary)

                expect(result.start.format('YYYY-MM-DD')).toBe('2024-01-09') // Tuesday (constrained)
                expect(result.end.format('YYYY-MM-DD')).toBe('2024-01-13') // Saturday (week end)
            })

            it('should constrain end date when boundary end is within week', () => {
                const referenceDate = dayjs('2024-01-10') // Wednesday
                const dateRangeBoundary = {
                    start: dayjs('2024-01-01'),
                    end: dayjs('2024-01-12'), // Friday
                }
                const result = getConstrainedWeekRange(referenceDate, dateRangeBoundary)

                expect(result.start.format('YYYY-MM-DD')).toBe('2024-01-07') // Sunday (week start)
                expect(result.end.format('YYYY-MM-DD')).toBe('2024-01-12') // Friday (constrained)
            })

            it('should constrain both start and end when boundary is within week', () => {
                const referenceDate = dayjs('2024-01-10') // Wednesday
                const dateRangeBoundary = {
                    start: dayjs('2024-01-09'), // Tuesday
                    end: dayjs('2024-01-11'), // Thursday
                }
                const result = getConstrainedWeekRange(referenceDate, dateRangeBoundary)

                expect(result.start.format('YYYY-MM-DD')).toBe('2024-01-09') // Tuesday (constrained)
                expect(result.end.format('YYYY-MM-DD')).toBe('2024-01-11') // Thursday (constrained)
            })

            it('should use week boundaries when date range is outside week', () => {
                const referenceDate = dayjs('2024-01-10') // Wednesday
                const dateRangeBoundary = {
                    start: dayjs('2024-01-01'),
                    end: dayjs('2024-01-31'),
                }
                const result = getConstrainedWeekRange(referenceDate, dateRangeBoundary)

                expect(result.start.format('YYYY-MM-DD')).toBe('2024-01-07') // Sunday (week start)
                expect(result.end.format('YYYY-MM-DD')).toBe('2024-01-13') // Saturday (week end)
            })

            it('should handle null date range boundary', () => {
                const referenceDate = dayjs('2024-01-10') // Wednesday
                const result = getConstrainedWeekRange(referenceDate, null)

                expect(result.start.format('YYYY-MM-DD')).toBe('2024-01-07') // Sunday
                expect(result.end.format('YYYY-MM-DD')).toBe('2024-01-13') // Saturday
            })

            it('should handle undefined date range boundary', () => {
                const referenceDate = dayjs('2024-01-10') // Wednesday
                const result = getConstrainedWeekRange(referenceDate)

                expect(result.start.format('YYYY-MM-DD')).toBe('2024-01-07') // Sunday
                expect(result.end.format('YYYY-MM-DD')).toBe('2024-01-13') // Saturday
            })

            it('should handle invalid date range boundary', () => {
                const referenceDate = dayjs('2024-01-10') // Wednesday
                const dateRangeBoundary = {
                    start: dayjs('invalid'),
                    end: dayjs('also-invalid'),
                }
                const result = getConstrainedWeekRange(referenceDate, dateRangeBoundary)

                expect(result.start.format('YYYY-MM-DD')).toBe('2024-01-07') // Sunday
                expect(result.end.format('YYYY-MM-DD')).toBe('2024-01-13') // Saturday
            })
        })

        describe('week start day variations', () => {
            it('should handle different week start days correctly', () => {
                const referenceDate = dayjs('2024-01-10') // Wednesday

                // Sunday start (default)
                const sundayResult = getConstrainedWeekRange(referenceDate, null, 0)
                expect(sundayResult.start.format('YYYY-MM-DD')).toBe('2024-01-07') // Sunday
                expect(sundayResult.end.format('YYYY-MM-DD')).toBe('2024-01-13') // Saturday

                // Monday start
                const mondayResult = getConstrainedWeekRange(referenceDate, null, 1)
                expect(mondayResult.start.format('YYYY-MM-DD')).toBe('2024-01-08') // Monday
                expect(mondayResult.end.format('YYYY-MM-DD')).toBe('2024-01-14') // Sunday
            })

            it('should handle cached reference date adjustment', () => {
                // Simulate a cached Sunday reference date when week start changes to Monday
                const sundayReference = dayjs('2024-01-07') // Sunday
                const result = getConstrainedWeekRange(sundayReference, null, 1)

                // Should adjust Sunday to Monday
                expect(result.start.format('YYYY-MM-DD')).toBe('2024-01-08') // Monday
                expect(result.end.format('YYYY-MM-DD')).toBe('2024-01-14') // Sunday
            })

            it('should handle cached reference date adjustment for Monday to Sunday', () => {
                // Simulate a cached Monday reference date when week start changes to Sunday
                const mondayReference = dayjs('2024-01-08') // Monday
                const result = getConstrainedWeekRange(mondayReference, null, 0)

                // Should adjust Monday to Sunday
                expect(result.start.format('YYYY-MM-DD')).toBe('2024-01-07') // Sunday
                expect(result.end.format('YYYY-MM-DD')).toBe('2024-01-13') // Saturday
            })

            it('should handle cached reference date adjustment with out of bounds date range', () => {
                // Simulate a cached Monday reference date when week start changes to Sunday
                const mondayReference = dayjs('2025-06-02') // Monday
                const dateRangeBoundary = {
                    // In the cached data, the date range is from the Monday of the week, which makes the reference within bounds if the week starts on Monday
                    // But if the week starts on Sunday, it will be out of bounds (will be on the previous week)
                    start: dayjs('2025-06-09'),
                    end: dayjs('2025-06-11'),
                }
                const result = getConstrainedWeekRange(mondayReference, dateRangeBoundary, 0)

                // Should ignore the boundary and return the week starting from the previous Sunday
                expect(result.start.format('YYYY-MM-DD')).toBe('2025-06-01') // Sunday of previous week
                expect(result.end.format('YYYY-MM-DD')).toBe('2025-06-07') // Saturday of previous week
            })
        })

        describe('return value validation', () => {
            it('should always return valid dayjs objects', () => {
                const referenceDate = dayjs('2024-01-10')
                const result = getConstrainedWeekRange(referenceDate)

                expect(result.start.isValid()).toBe(true)
                expect(result.end.isValid()).toBe(true)
            })

            it('should ensure end is not before start', () => {
                const referenceDate = dayjs('2024-01-10')
                const result = getConstrainedWeekRange(referenceDate)

                expect(result.start.isSameOrBefore(result.end)).toBe(true)
            })

            it('should return objects with correct structure', () => {
                const referenceDate = dayjs('2024-01-10')
                const result = getConstrainedWeekRange(referenceDate)

                expect(result).toHaveProperty('start')
                expect(result).toHaveProperty('end')
                expect(typeof result.start.format).toBe('function')
                expect(typeof result.end.format).toBe('function')
            })
        })
    })

    describe('formatLocalizedDate', () => {
        const originalLanguage = Object.getOwnPropertyDescriptor(window.navigator, 'language')
        const originalLang = document.documentElement.lang

        afterEach(() => {
            if (originalLanguage) {
                Object.defineProperty(window.navigator, 'language', originalLanguage)
            }
            document.documentElement.lang = originalLang
        })

        it('should return US date format for en-US locale', () => {
            Object.defineProperty(window.navigator, 'language', { value: 'en-US', configurable: true })
            expect(formatLocalizedDate()).toBe('MMM DD')
        })

        it('should return US date format for en-CA locale', () => {
            Object.defineProperty(window.navigator, 'language', { value: 'en-CA', configurable: true })
            expect(formatLocalizedDate()).toBe('MMM DD')
        })

        it('should return international date format for en-GB locale', () => {
            Object.defineProperty(window.navigator, 'language', { value: 'en-GB', configurable: true })
            expect(formatLocalizedDate()).toBe('DD MMM')
        })

        it('should handle locale with region suffix', () => {
            Object.defineProperty(window.navigator, 'language', { value: 'en-US-x-custom', configurable: true })
            expect(formatLocalizedDate()).toBe('MMM DD')
        })

        it('should handle locale without region (defaults to international format)', () => {
            Object.defineProperty(window.navigator, 'language', { value: 'en', configurable: true })
            expect(formatLocalizedDate()).toBe('DD MMM')
        })

        it('should fall back to document.documentElement.lang when navigator.language is undefined', () => {
            Object.defineProperty(window.navigator, 'language', { value: undefined, configurable: true })
            document.documentElement.lang = 'en-GB'
            expect(formatLocalizedDate()).toBe('DD MMM')
        })
    })

    describe('alignResolvedDateRangeToInterval', () => {
        it('returns undefined when resolvedDateRange is missing', () => {
            expect(alignResolvedDateRangeToInterval(undefined, 'month')).toBeUndefined()
            expect(alignResolvedDateRangeToInterval(null, 'month')).toBeUndefined()
        })

        it('returns undefined when date_from is empty', () => {
            expect(
                alignResolvedDateRangeToInterval({ date_from: '', date_to: '2026-04-07T23:59:59+00:00' }, 'month')
            ).toBeUndefined()
        })

        it.each([['day' as const], [null], [undefined]])(
            'returns the range unchanged when interval is %s',
            (interval) => {
                const range = {
                    date_from: '2025-04-07T00:00:00+00:00',
                    date_to: '2026-04-07T23:59:59+00:00',
                }
                expect(alignResolvedDateRangeToInterval(range, interval)).toBe(range)
            }
        )

        it('expands to full months when grouping by month', () => {
            expect(
                alignResolvedDateRangeToInterval(
                    {
                        date_from: '2025-04-07T00:00:00+00:00',
                        date_to: '2026-04-07T23:59:59+00:00',
                    },
                    'month'
                )
            ).toEqual({
                date_from: '2025-04-01T00:00:00+00:00',
                date_to: '2026-04-30T23:59:59+00:00',
            })
        })

        it('preserves a non-UTC timezone offset', () => {
            expect(
                alignResolvedDateRangeToInterval(
                    {
                        date_from: '2025-04-07T00:00:00-08:00',
                        date_to: '2026-04-07T23:59:59-08:00',
                    },
                    'month'
                )
            ).toEqual({
                date_from: '2025-04-01T00:00:00-08:00',
                date_to: '2026-04-30T23:59:59-08:00',
            })
        })

        it('normalizes a Z suffix to +00:00', () => {
            expect(
                alignResolvedDateRangeToInterval(
                    {
                        date_from: '2025-04-07T00:00:00Z',
                        date_to: '2026-04-07T23:59:59Z',
                    },
                    'month'
                )
            ).toEqual({
                date_from: '2025-04-01T00:00:00+00:00',
                date_to: '2026-04-30T23:59:59+00:00',
            })
        })

        it('handles an ISO string with no timezone suffix', () => {
            expect(
                alignResolvedDateRangeToInterval(
                    {
                        date_from: '2025-04-07T00:00:00',
                        date_to: '2026-04-07T23:59:59',
                    },
                    'month'
                )
            ).toEqual({
                date_from: '2025-04-01T00:00:00',
                date_to: '2026-04-30T23:59:59',
            })
        })
    })

    describe('parseDateInTimezone', () => {
        describe('date-only strings', () => {
            it.each([
                ['UTC', '+00:00'],
                ['America/Los_Angeles', '-07:00'],
                ['Asia/Tokyo', '+09:00'],
                ['Europe/Berlin', '+02:00'],
            ])('treats "2026-05-05" as wall-clock midnight in project tz %s', (timezone, expectedOffset) => {
                const out = parseDateInTimezone('2026-05-05', timezone)
                expect(out.format('YYYY-MM-DD HH:mm Z')).toEqual(`2026-05-05 00:00 ${expectedOffset}`)
            })

            it('returns the same calendar day across browser timezones (no DST drift)', () => {
                // The chart x-axis renders this with a 'D MMM' or 'MMM D' format.
                // Across DST boundaries and across browser timezones, the calendar day
                // for a date-only string must not shift by ±1 day.
                const out = parseDateInTimezone('2026-03-08', 'America/Los_Angeles')
                expect(out.format('D MMM YYYY')).toEqual('8 Mar 2026')
            })
        })

        describe('strings with explicit timezone offset', () => {
            it('treats Z-suffixed timestamps as real instants and converts to project tz', () => {
                // 2024-04-28 23:30 UTC = 2024-04-29 08:30 in Tokyo.
                const out = parseDateInTimezone('2024-04-28T23:30:00Z', 'Asia/Tokyo')
                expect(out.format('YYYY-MM-DD HH:mm Z')).toEqual('2024-04-29 08:30 +09:00')
            })

            it('treats +HH:MM offsets as real instants', () => {
                // 2024-04-28 00:00 -07:00 = 2024-04-28 07:00 UTC = 2024-04-28 16:00 Tokyo.
                const out = parseDateInTimezone('2024-04-28T00:00:00-07:00', 'Asia/Tokyo')
                expect(out.format('YYYY-MM-DD HH:mm Z')).toEqual('2024-04-28 16:00 +09:00')
            })
        })

        describe('invalid inputs', () => {
            it('returns an invalid Dayjs for unparseable strings instead of throwing', () => {
                const out = parseDateInTimezone('not-a-date', 'UTC')
                expect(dayjs.isDayjs(out)).toBe(true)
                expect(out.isValid()).toBe(false)
            })
        })
    })
})
