import React from 'react'
import './InsightTooltip.scss'

interface BodyLine {
    id: string
    component: JSX.Element
    borderColor: string
    backgroundColor: string | false
}

interface InsightTooltipProps {
    titleLines: string[]
    bodyLines: BodyLine[]
    inspectUsersLabel?: boolean
}

export function InsightTooltip({ titleLines, bodyLines, inspectUsersLabel }: InsightTooltipProps): JSX.Element {
    return (
        <>
            {titleLines.map((title, i) => (
                <header key={i}>{title}</header>
            ))}
            <ul>
                {bodyLines.map((line, i) => {
                    const iconColor = line.backgroundColor || line.borderColor
                    return (
                        <li key={i}>
                            <div className="color-icon" style={{ background: iconColor }} />
                            <div className="title">{line.component}</div>
                        </li>
                    )
                })}
            </ul>
            {inspectUsersLabel && <footer>Click to inspect users</footer>}
        </>
    )
}
