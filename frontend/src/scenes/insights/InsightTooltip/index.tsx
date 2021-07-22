import { DateDisplay } from 'lib/components/DateDisplay'
import { IconHandClick } from 'lib/components/icons'
import React from 'react'
import { IntervalType } from '~/types'
import './InsightTooltip.scss'

interface BodyLine {
    id?: string | number
    component: JSX.Element
}

interface InsightTooltipProps {
    chartType: string
    altTitle?: string | JSX.Element | null // Alternate string to display as title (in case date reference is not available or not desired)
    referenceDate?: string
    interval?: IntervalType
    bodyLines?: BodyLine[] // bodyLines is in here for its similarity to LineChart's built-in tooltips, but children is easier to use in other React components
    inspectUsersLabel?: boolean
    children?: React.ReactNode
}

export function InsightTooltip({
    chartType,
    altTitle,
    referenceDate,
    interval,
    bodyLines = [],
    inspectUsersLabel,
    children,
}: InsightTooltipProps): JSX.Element {
    return (
        <div className={`inner-tooltip${bodyLines.length > 1 ? ' multiple' : ''}`} style={{ maxWidth: 300 }}>
            {chartType !== 'horizontalBar' && (
                <header>
                    {referenceDate && interval ? <DateDisplay interval={interval} date={referenceDate} /> : altTitle}
                </header>
            )}
            {bodyLines?.length > 0 && (
                <ul>
                    {bodyLines.map((line, index) => (
                        <li key={line.id ?? index}>{line.component}</li>
                    ))}
                </ul>
            )}
            {children}
            {inspectUsersLabel && (
                <footer>
                    <IconHandClick /> Click to inspect users
                </footer>
            )}
        </div>
    )
}
