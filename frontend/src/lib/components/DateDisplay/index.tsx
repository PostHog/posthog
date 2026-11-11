import './DateDisplay.scss'

import { ResolvedDateRangeResponse } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import { dateDisplayParts } from './dateDisplayParts'

interface DateDisplayProps {
    date: string
    secondaryDate?: string
    interval: IntervalType
    hideWeekRange?: boolean
    resolvedDateRange?: ResolvedDateRangeResponse
    timezone?: string
    weekStartDay?: number
}

/* Returns a single line standardized component to display the date depending on context.
    For example, a single date in a graph will be shown as: `Th` Apr 22.
*/
export function DateDisplay({ hideWeekRange, ...input }: DateDisplayProps): JSX.Element {
    const { highlight, date, secondaryDate, weekEnd } = dateDisplayParts(input)

    return (
        <>
            <span className="dated-highlight">{highlight}</span>
            {secondaryDate && <br />}
            <span className="date-display-dates">
                {date}
                {secondaryDate && <span className="secondary-date">({secondaryDate})</span>}
            </span>
            {input.interval === 'week' && !hideWeekRange && weekEnd && (
                <>
                    {' – '}
                    <DateDisplay interval="day" date={weekEnd.toJSON()} timezone={input.timezone} />
                </>
            )}
        </>
    )
}
