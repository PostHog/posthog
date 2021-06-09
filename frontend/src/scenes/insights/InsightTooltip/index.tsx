import { DateDisplay } from 'lib/components/DateDisplay'
import React from 'react'
import { IntervalType } from '~/types'
import './InsightTooltip.scss'

interface BodyLine {
    id: string
    component: JSX.Element
    borderColor: string
    backgroundColor: string | false
}

interface InsightTooltipProps {
    altTitle?: string // Alternate string to display as title (in case date reference is not available, e.g. when comparing previous)
    referenceDate?: string
    interval: IntervalType
    bodyLines: BodyLine[]
    inspectUsersLabel?: boolean
}

export function InsightTooltip({
    altTitle,
    referenceDate,
    interval,
    bodyLines,
    inspectUsersLabel,
}: InsightTooltipProps): JSX.Element {
    return (
        <>
            <header>{referenceDate ? <DateDisplay interval={interval} date={referenceDate} /> : altTitle}</header>

            <ul>
                {bodyLines.map((line, i) => {
                    return <li key={i}>{line.component}</li>
                })}
            </ul>

            {inspectUsersLabel && <footer>Click to inspect users</footer>}
        </>
    )
}
