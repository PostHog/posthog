import { Collapsible } from '@base-ui/react/collapsible'
import type { MouseEvent } from 'react'

import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { isPlainClick, navigateWithCrossfade } from './todayViewTransition'

function isExternalHref(href: string): boolean {
    return /^https?:\/\//.test(href)
}

/**
 * A cut reason shows in full in a tooltip on the title, not on the cut line, because the title's link covers the
 * whole row and takes every hover.
 */
export function TodayRowTitle({
    title,
    to,
    onOpen,
    expandable,
    reason,
    reasonTruncated,
    reportId,
    dataAttr,
}: {
    title: string
    to?: string
    onOpen?: () => void
    expandable: boolean
    reason?: string | null
    reasonTruncated: boolean
    reportId?: string
    dataAttr: string
}): JSX.Element {
    const openReport = (event: MouseEvent<HTMLElement>): void => {
        onOpen?.()
        if (to && reportId && isPlainClick(event)) {
            event.preventDefault()
            navigateWithCrossfade(to)
        }
    }
    const control = expandable ? (
        <Collapsible.Trigger
            className="TodayRow__title TodayRow__link TodayRow__toggle"
            data-today-report={reportId}
            data-attr={`${dataAttr}-toggle`}
        >
            {title}
        </Collapsible.Trigger>
    ) : to ? (
        <LinkPrimitive
            to={to}
            target={isExternalHref(to) ? '_blank' : undefined}
            className="TodayRow__title TodayRow__link"
            onClick={openReport}
            data-today-report={reportId}
            data-attr={dataAttr}
        >
            {title}
        </LinkPrimitive>
    ) : (
        <span className="TodayRow__title">{title}</span>
    )
    if (!reason) {
        return control
    }
    return (
        <Tooltip disabled={!reasonTruncated}>
            <TooltipTrigger render={control} />
            <TooltipContent align="start" className="max-w-80">
                {reason}
            </TooltipContent>
        </Tooltip>
    )
}
