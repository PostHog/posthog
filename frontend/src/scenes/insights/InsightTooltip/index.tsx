import { DateDisplay } from 'lib/components/DateDisplay'
import { hexToRGBA } from 'lib/utils'
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
                    const iconColor = line.backgroundColor || line.borderColor
                    return (
                        <li key={i}>
                            <div
                                className="color-icon"
                                style={{
                                    background: iconColor,
                                    boxShadow: `0px 0px 0px 1px ${hexToRGBA(iconColor, 0.5)}`,
                                }}
                            />
                            <div className="title">{line.component}</div>
                        </li>
                    )
                })}
            </ul>
            {inspectUsersLabel && <footer>Click to inspect users</footer>}
        </>
    )
}
