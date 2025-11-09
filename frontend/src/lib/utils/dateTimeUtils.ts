import { dayjs } from 'lib/dayjs'

export interface DayJSDateRange {
    start: dayjs.Dayjs
    end: dayjs.Dayjs
}

/**
 * Get week boundaries for a reference date constrained by a date range.
 */
export function getConstrainedWeekRange(
    referenceDate: dayjs.Dayjs,
    dateRangeBoundary?: DayJSDateRange | null,
    weekStartDay: number = 0 // 0 for Sunday, 1 for Monday
): DayJSDateRange {
    dayjs.updateLocale('en', {
        weekStart: weekStartDay,
    })

    // Prevent an edge case where the reference date is not set to the start of the week
    // This can happen when the data is cached and the weekStartDay changes
    if ([0, 1].includes(referenceDate.day()) && referenceDate.day() !== weekStartDay) {
        // adjust the reference date to the start of the week
        referenceDate = referenceDate.add(weekStartDay - referenceDate.day(), 'day')
    }

    const weekStart = referenceDate.startOf('week')
    const weekEnd = referenceDate.endOf('week')

    if (dateRangeBoundary && dateRangeBoundary.start.isValid() && dateRangeBoundary.end.isValid()) {
        return {
            start:
                dateRangeBoundary.start.isAfter(weekStart) && dateRangeBoundary.start.isBefore(weekEnd)
                    ? dateRangeBoundary.start
                    : weekStart,
            end:
                dateRangeBoundary.end.isBefore(weekEnd) && dateRangeBoundary.end.isAfter(weekStart)
                    ? dateRangeBoundary.end
                    : weekEnd,
        }
    }

    return {
        start: weekStart,
        end: weekEnd,
    }
}

export function getLocalizedDateFormat(): string {
    try {
        const locale = navigator.language || 'en-US'
        const usLocales = ['en-US', 'en-CA', 'en-AU', 'en-NZ']
        const isUSFormat = usLocales.some(usLocale => locale.startsWith(usLocale.split('-')[0]))
        return isUSFormat ? 'MMM D' : 'D MMM'
    } catch (error) {
        return 'MMM D'
    }
}
