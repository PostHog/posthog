import { dayjs } from 'lib/dayjs'
import { getConstrainedWeekRange } from 'lib/utils/datetime'

import { ResolvedDateRangeResponse } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

export interface DateDisplayInput {
    date: string
    secondaryDate?: string
    interval: IntervalType
    resolvedDateRange?: ResolvedDateRangeResponse
    timezone?: string
    weekStartDay?: number
}

export interface DateDisplayParts {
    /** The weekday, or the year for coarse intervals, as in `Th`. Empty for a yearly interval. */
    highlight: string
    date: string
    secondaryDate?: string
    /** The last day of a weekly bucket, clipped to the date range. */
    weekEnd: dayjs.Dayjs | null
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

const dateHighlight = (parsedDate: dayjs.Dayjs, interval: IntervalType): string => {
    switch (interval) {
        case 'second':
            return parsedDate.format('MMM D')
        case 'minute':
            return parsedDate.format('MMM D')
        case 'hour':
            return parsedDate.format('MMM D')
        case 'day':
            return parsedDate.format('dd')
        case 'week':
            return parsedDate.format('dd')
        case 'month':
            return parsedDate.format('YYYY')
        case 'quarter':
            return parsedDate.format('YYYY')
        case 'year':
            return ''
        default:
            return parsedDate.format('dd')
    }
}

export function dateDisplayParts({
    date,
    secondaryDate,
    interval,
    resolvedDateRange,
    timezone,
    weekStartDay,
}: DateDisplayInput): DateDisplayParts {
    let parsedDate = dayjs.tz(date, timezone)
    let weekEnd = null

    if (interval === 'week' && resolvedDateRange) {
        const dateFrom = dayjs.tz(resolvedDateRange.date_from, timezone)
        const dateTo = dayjs.tz(resolvedDateRange.date_to, timezone)
        const weekBoundaries = getConstrainedWeekRange(parsedDate, { start: dateFrom, end: dateTo }, weekStartDay || 0)
        parsedDate = weekBoundaries.start
        weekEnd = weekBoundaries.end
    }

    return {
        highlight: dateHighlight(parsedDate, interval),
        date: parsedDate.format(DISPLAY_DATE_FORMAT[interval]),
        secondaryDate: secondaryDate ? dayjs(secondaryDate).format(DISPLAY_DATE_FORMAT[interval]) : undefined,
        weekEnd,
    }
}
