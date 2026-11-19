import { Collapsible } from '@base-ui/react/collapsible'
import { type MouseEvent, type ReactNode, useState } from 'react'

import { IconArrowRight, IconChevronDown } from '@posthog/icons'
import { IconStack, IconStackItem, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { TodayRowIcon } from './todayRowIcons'
import { TodayRowMeta } from './TodayRowMeta'
import { isPlainClick, navigateWithCrossfade } from './todayViewTransition'

function isExternalHref(href: string): boolean {
    return /^https?:\/\//.test(href)
}

export type TodayRowTone = 'risk' | 'neutral' | 'quiet'

interface TodayRowExpansion {
    expanded: boolean
    onToggle: () => void
    detail: ReactNode
}

interface TodayRowProps {
    tone: TodayRowTone
    icon: TodayRowIcon
    title: string
    label?: string
    facts: string[]
    /** Why the personal ranking placed the row, shown after the facts. */
    reason?: string | null
    to?: string
    onOpen?: () => void
    expansion?: TodayRowExpansion
    actions?: ReactNode
    doneActions?: ReactNode
    done?: boolean
    reportId?: string
    dataAttr: string
}

export function TodayRow({
    tone,
    icon,
    title,
    label,
    facts,
    reason,
    to,
    onOpen,
    expansion,
    actions,
    doneActions,
    done,
    reportId,
    dataAttr,
}: TodayRowProps): JSX.Element {
    const external = !!to && isExternalHref(to)
    const expanded = !!expansion?.expanded
    const [reasonTruncated, setReasonTruncated] = useState(false)
    const openReport = (event: MouseEvent<HTMLElement>): void => {
        onOpen?.()
        if (to && reportId && isPlainClick(event)) {
            event.preventDefault()
            navigateWithCrossfade(to)
        }
    }
    const titleControl = expansion ? (
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
            target={external ? '_blank' : undefined}
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
    const content = (
        <>
            <IconStack className="TodayRow__icons">
                <IconStackItem color={icon.color}>{icon.glyph}</IconStackItem>
            </IconStack>
            <div className="min-w-0">
                {reason ? (
                    <Tooltip disabled={!reasonTruncated}>
                        <TooltipTrigger render={titleControl} />
                        <TooltipContent align="start" className="max-w-80">
                            {reason}
                        </TooltipContent>
                    </Tooltip>
                ) : (
                    titleControl
                )}
                <TodayRowMeta
                    tone={tone}
                    label={label}
                    facts={facts}
                    reason={reason}
                    onTruncatedChange={setReasonTruncated}
                />
            </div>
            <div className="TodayRow__end">
                {actions && !done && !expanded && <div className="TodayRow__actions">{actions}</div>}
                {doneActions && done && <div className="TodayRow__undo">{doneActions}</div>}
                {expansion ? (
                    <IconChevronDown className="TodayRow__chevron" aria-hidden />
                ) : (
                    to && <IconArrowRight className="TodayRow__arrow" aria-hidden />
                )}
            </div>
            {expansion && <Collapsible.Panel className="TodayRow__detail">{expansion.detail}</Collapsible.Panel>}
        </>
    )
    const rowProps = {
        className: 'TodayRow',
        'data-interactive': to || expansion ? true : undefined,
        'data-expanded': expanded || undefined,
        'data-done': done || undefined,
    }
    if (!expansion) {
        return <li {...rowProps}>{content}</li>
    }
    return (
        <Collapsible.Root open={expanded} onOpenChange={expansion.onToggle} render={<li {...rowProps} />}>
            {content}
        </Collapsible.Root>
    )
}
