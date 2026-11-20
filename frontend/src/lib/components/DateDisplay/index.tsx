import './DateDisplay.scss'

import { ResolvedDateRangeResponse } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import { formatDateDisplay } from './formatDateDisplay'

interface DateDisplayProps {
    date: string
    secondaryDate?: string
    interval: IntervalType
    hideWeekRange?: boolean
    resolvedDateRange?: ResolvedDateRangeResponse
    timezone?: string
    weekStartDay?: number
    /** Show a three-letter weekday, and the year when it is not the current year in the project timezone. */
    showFullDate?: boolean
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
    showFullDate,
}: DateDisplayProps): JSX.Element {
    const { highlight, primary, secondary, weekEnd } = formatDateDisplay({
        date,
        interval,
        secondaryDate,
        resolvedDateRange,
        timezone,
        weekStartDay,
        showFullDate,
    })

    return (
        <>
            <span className="dated-highlight">{highlight}</span>
            {secondary !== null && <br />}
            <span className="date-display-dates">
                {primary}
                {secondary !== null && <span className="secondary-date">({secondary})</span>}
            </span>
            {interval === 'week' && !hideWeekRange && weekEnd && (
                <>
                    {' – '}
                    <DateDisplay interval="day" date={weekEnd} timezone={timezone} showFullDate={showFullDate} />
                </>
            )}
        </>
    )
}
