import { dayjs } from 'lib/dayjs'

export interface DayJSDateRange {
    dateFrom: dayjs.Dayjs
    dateTo: dayjs.Dayjs
}

export interface WeekBoundaries {
    weekStart: dayjs.Dayjs
    weekEnd: dayjs.Dayjs
}

/**
 * Calculate bounded start and end dates for a week interval
 */
export function getWeekBoundaries(
    referenceDate: dayjs.Dayjs,
    dateRangeBoundary?: DayJSDateRange | null,
    weekStartDay: number = 0 // 0 for Sunday, 1 for Monday
): WeekBoundaries {
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

    if (dateRangeBoundary) {
        return {
            weekStart:
                dateRangeBoundary.dateFrom.isAfter(weekStart) && dateRangeBoundary.dateFrom.isBefore(weekEnd)
                    ? dateRangeBoundary.dateFrom
                    : weekStart,
            weekEnd:
                dateRangeBoundary.dateTo.isBefore(weekEnd) && dateRangeBoundary.dateTo.isAfter(weekStart)
                    ? dateRangeBoundary.dateTo
                    : weekEnd,
        }
    }

    return {
        weekStart,
        weekEnd: weekEnd.isBefore(weekStart) ? weekStart : weekEnd, // Ensure weekEnd is not before weekStart
    }
}
