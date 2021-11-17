import { dayjs } from 'lib/dayjs'
import React from 'react'
import { IntervalType } from '~/types'
import './DateDisplay.scss'

interface DateDisplayProps {
    date: string
    interval: IntervalType
    hideWeekRange?: boolean
}

const DISPLAY_DATE_FORMAT: Record<IntervalType, string> = {
    minute: 'HH:mm',
    hour: 'HH:00',
    day: 'MMM D',
    week: 'MMM D',
    month: 'MMM',
}

const dateHighlight = (parsedDate: dayjs.Dayjs, interval: IntervalType): string => {
    switch (interval) {
        case 'minute':
            return parsedDate.format('DD')
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
export function DateDisplay({ date, interval, hideWeekRange }: DateDisplayProps): JSX.Element {
    const parsedDate = dayjs(date)

    return (
        <>
            <span className="dated-highlight">{dateHighlight(parsedDate, interval)}</span>
            {parsedDate.format(DISPLAY_DATE_FORMAT[interval])}
            {interval === 'week' && !hideWeekRange && (
                <>
                    {/* TODO: @EDsCODE will help validate; this should probably come from the backend  */}
                    {' - '}
                    <DateDisplay interval="day" date={parsedDate.add(7, 'day').toJSON()} />
                </>
            )}
        </>
    )
}
