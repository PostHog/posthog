import './DateDisplay.scss'

import { dayjs } from 'lib/dayjs'
import { getConstrainedWeekRange } from 'lib/utils/dateTimeUtils'

import { ResolvedDateRangeResponse } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

interface DateDisplayProps {
    date: string
    secondaryDate?: string
    interval: IntervalType
    hideWeekRange?: boolean
    resolvedDateRange?: ResolvedDateRangeResponse
    timezone?: string
    weekStartDay?: number
}

const DISPLAY_DATE_FORMAT: Record<IntervalType, string> = {
    minute: 'HH:mm:00',
    hour: 'HH:00',
    day: 'D MMM',
    week: 'D MMM',
    month: 'MMM',
}

const dateHighlight = (parsedDate: dayjs.Dayjs, interval: IntervalType): string => {
    switch (interval) {
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
        default:
            return parsedDate.format('dd')
    }
}

/* Returns a single line standardized component to display the date depending on context.
    For example, a single date in a graph will be shown as: `Th` Apr 22.
*/
export function DateDisplay({
    date,
    secondaryDate,
    interval,
    hideWeekRange,
    resolvedDateRange,
    timezone,
    weekStartDay,
}: DateDisplayProps): JSX.Element {
    let parsedDate = dayjs.tz(date, timezone)
    let weekEnd = null

    if (interval === 'week' && resolvedDateRange) {
        const dateFrom = dayjs.tz(resolvedDateRange.date_from, timezone)
        const dateTo = dayjs.tz(resolvedDateRange.date_to, timezone)
        const weekBoundaries = getConstrainedWeekRange(parsedDate, { start: dateFrom, end: dateTo }, weekStartDay || 0)
        parsedDate = weekBoundaries.start
        weekEnd = weekBoundaries.end
    }

    return (
        <>
            <span className="dated-highlight">{dateHighlight(parsedDate, interval)}</span>
            {secondaryDate && <br />}
            <span className="date-display-dates">
                {parsedDate.format(DISPLAY_DATE_FORMAT[interval])}
                {secondaryDate && (
                    <span className="secondary-date">
                        ({dayjs(secondaryDate).format(DISPLAY_DATE_FORMAT[interval])})
                    </span>
                )}
            </span>
            {interval === 'week' && !hideWeekRange && weekEnd && (
                <>
                    {' – '}
                    <DateDisplay interval="day" date={weekEnd.toJSON()} timezone={timezone} />
                </>
            )}
        </>
    )
}
