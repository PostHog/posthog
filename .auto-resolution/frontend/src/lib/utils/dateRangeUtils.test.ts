import { dayjs } from 'lib/dayjs'

import { getConstrainedWeekRange } from './dateTimeUtils'

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
