import { DateDisplay } from 'lib/components/DateDisplay'
import { IconHandClick } from 'lib/components/icons'
import React from 'react'
import { IntervalType } from '~/types'
import './InsightTooltip.scss'

interface BodyLine {
    id: string
    component: JSX.Element
}

interface InsightTooltipProps {
    chartType: string
    altTitle?: string // Alternate string to display as title (in case date reference is not available, e.g. when comparing previous)
    referenceDate?: string
    interval: IntervalType
    bodyLines: BodyLine[]
    inspectUsersLabel?: boolean
}

export function InsightTooltip({
    chartType,
    altTitle,
    referenceDate,
    interval,
    bodyLines,
    inspectUsersLabel,
}: InsightTooltipProps): JSX.Element {
    return (
        <div className={`inner-tooltip${bodyLines.length > 1 ? ' multiple' : ''}`}>
            {chartType !== 'horizontalBar' && (
                <header>{referenceDate ? <DateDisplay interval={interval} date={referenceDate} /> : altTitle}</header>
            )}
            <ul>
                {bodyLines.map((line) => {
                    return <li key={line.id}>{line.component}</li>
                })}
            </ul>
            {inspectUsersLabel && (
                <footer>
                    <IconHandClick /> Click to inspect users
                </footer>
            )}
        </div>
    )
}
