import { dayjs } from 'lib/dayjs'
import { getConstrainedWeekRange } from 'lib/utils/datetime'

import { ResolvedDateRangeResponse } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

export interface FormatDateDisplayInput {
    date: string
    interval: IntervalType
    secondaryDate?: string
    resolvedDateRange?: ResolvedDateRangeResponse
    timezone?: string
    weekStartDay?: number
    showFullDate?: boolean
}

export interface DateDisplayParts {
    highlight: string
    primary: string
    secondary: string | null
    weekEnd: string | null
}

const DISPLAY_DATE_FORMAT: Record<IntervalType, string> = {
    second: 'HH:mm:ss',
    minute: 'HH:mm:00',
    hour: 'HH:00',
    day: 'D MMM',
    week: 'D MMM',
    month: 'MMM',
    quarter: '[Q]Q',
    year: 'YYYY',
}

// Compare with today in the project timezone, because near New Year the browser timezone can be in another year.
const isOutsideCurrentYear = (parsedDate: dayjs.Dayjs, timezone: string | undefined): boolean =>
    parsedDate.year() !== dayjs().tz(timezone).year()

const monthFirstDateFormat = (showYear: boolean): string => (showYear ? 'MMM D, YYYY' : 'MMM D')

const dateHighlight = (
    parsedDate: dayjs.Dayjs,
    interval: IntervalType,
    showFullDate: boolean,
    showYear: boolean
): string => {
    const weekdayFormat = showFullDate ? 'ddd' : 'dd'
    switch (interval) {
        case 'second':
        case 'minute':
        case 'hour':
            return parsedDate.format(monthFirstDateFormat(showYear))
        case 'day':
        case 'week':
            return parsedDate.format(weekdayFormat)
        case 'month':
        case 'quarter':
            return parsedDate.format('YYYY')
        case 'year':
            return ''
        default:
            return parsedDate.format(weekdayFormat)
    }
}

const primaryDateFormat = (interval: IntervalType, showYear: boolean): string =>
    showYear && (interval === 'day' || interval === 'week') ? 'D MMM YYYY' : DISPLAY_DATE_FORMAT[interval]

export function formatDateDisplay({
    date,
    interval,
    secondaryDate,
    resolvedDateRange,
    timezone,
    weekStartDay,
    showFullDate = false,
}: FormatDateDisplayInput): DateDisplayParts {
    let parsedDate = dayjs.tz(date, timezone)
    let weekEnd: string | null = null

    if (interval === 'week' && resolvedDateRange) {
        const dateFrom = dayjs.tz(resolvedDateRange.date_from, timezone)
        const dateTo = dayjs.tz(resolvedDateRange.date_to, timezone)
        const weekBoundaries = getConstrainedWeekRange(parsedDate, { start: dateFrom, end: dateTo }, weekStartDay || 0)
        parsedDate = weekBoundaries.start
        weekEnd = weekBoundaries.end.toJSON()
    }

    const showYear = showFullDate && isOutsideCurrentYear(parsedDate, timezone)

    return {
        highlight: dateHighlight(parsedDate, interval, showFullDate, showYear),
        primary: parsedDate.format(primaryDateFormat(interval, showYear)),
        secondary: secondaryDate ? dayjs(secondaryDate).format(DISPLAY_DATE_FORMAT[interval]) : null,
        weekEnd,
    }
}
