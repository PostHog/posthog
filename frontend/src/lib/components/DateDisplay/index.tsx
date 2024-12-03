import './DateDisplay.scss'

import { dayjs } from 'lib/dayjs'

import { IntervalType } from '~/types'

interface DateDisplayProps {
    date: string
    secondaryDate?: string
    interval: IntervalType
    hideWeekRange?: boolean
}

const DISPLAY_DATE_FORMAT: Record<IntervalType, string> = {
    minute: 'HH:mm:00',
    hour: 'HH:00',
    day: 'MMM D',
    week: 'MMM D',
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
export function DateDisplay({ date, secondaryDate, interval, hideWeekRange }: DateDisplayProps): JSX.Element {
    const parsedDate = dayjs.utc(date)

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
