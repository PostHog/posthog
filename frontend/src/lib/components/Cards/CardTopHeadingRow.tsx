import React from 'react'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

export function CardTopHeadingRow({
    typeLabel,
    typeTitle,
    showTypeLabel = true,
    dateText,
    dateTooltip,
    separateChildren = false,
    children,
}: {
    typeLabel?: string | null
    typeTitle?: string
    showTypeLabel?: boolean
    dateText?: string | null
    dateTooltip?: string | null
    /** Render a • before children when a label/date precedes; leave off for inline adornments (e.g. the freshness clock). */
    separateChildren?: boolean
    children?: React.ReactNode
}): JSX.Element | null {
    const showLabelSegment = Boolean(showTypeLabel && typeLabel)
    const hasChildren = React.Children.toArray(children).length > 0

    if (!showLabelSegment && !dateText && !hasChildren) {
        return null
    }

    return (
        <div className="flex items-center gap-1">
            {showLabelSegment ? <span title={typeTitle ?? typeLabel ?? undefined}>{typeLabel}</span> : null}
            {dateText ? (
                <>
                    {showLabelSegment ? <span>•</span> : null}
                    {dateTooltip ? (
                        <Tooltip title={dateTooltip}>
                            <span className="whitespace-nowrap">{dateText}</span>
                        </Tooltip>
                    ) : (
                        <span className="whitespace-nowrap">{dateText}</span>
                    )}
                </>
            ) : null}
            {hasChildren ? (
                <>
                    {separateChildren && (showLabelSegment || dateText) ? <span>•</span> : null}
                    {children}
                </>
            ) : null}
        </div>
    )
}
