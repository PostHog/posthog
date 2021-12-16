import './InsightTooltip.scss'
import React from 'react'
import { dayjs } from 'lib/dayjs'

interface BodyLine {
    id?: string | number
    component: React.ReactNode
}

interface InsightTooltipProps {
    referenceDate?: string // If referenceDate is undefined, altTitle must be provided
    altTitle?: string // Overrides showing the referenceDate as the title
    useAltTitle?: boolean
    hideHeader?: boolean
    hideInspectActorsSection?: boolean
    bodyLines?: BodyLine[]
    children?: React.ReactNode
}

function getTitle(dayString?: string, altTitle?: string, useAltTitle?: boolean): string {
    const day = dayjs(dayString)
    if (dayString !== undefined && !useAltTitle && day.isValid()) {
        return day.format('DD MMM YYYY')
    }
    return altTitle ?? ''
}

export function InsightTooltip({
    referenceDate,
    altTitle,
    children,
    bodyLines = [],
    useAltTitle = false,
    hideHeader: _hideHeader = false,
    hideInspectActorsSection = true,
}: InsightTooltipProps): JSX.Element {
    const hideHeader = _hideHeader || (referenceDate === undefined && altTitle === undefined) // both referenceDate and altTitle are undefined
    const title = hideHeader ? '' : getTitle(referenceDate, altTitle, useAltTitle)

    return (
        <div>
            {!hideHeader && <div>{title}</div>}
            {bodyLines.map(({ id, component }) => (
                <ul key={id}>{component}</ul>
            ))}
            {children}
            {!hideInspectActorsSection && <div>Click to inspect</div>}
        </div>
    )
}
