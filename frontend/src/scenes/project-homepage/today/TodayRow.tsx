import { Collapsible } from '@base-ui/react/collapsible'
import type { MouseEvent, ReactNode } from 'react'

import { IconArrowRight, IconChevronDown } from '@posthog/icons'
import { IconStack, IconStackItem } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { TodayRowIcon } from './todayRowIcons'
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
    const openReport = (event: MouseEvent<HTMLElement>): void => {
        onOpen?.()
        if (to && reportId && isPlainClick(event)) {
            event.preventDefault()
            navigateWithCrossfade(to)
        }
    }
    const content = (
        <>
            <IconStack className="TodayRow__icons">
                <IconStackItem color={icon.color}>{icon.glyph}</IconStackItem>
            </IconStack>
            <div className="min-w-0">
                {expansion ? (
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
                )}
                <p className="TodayRow__meta">
                    {[label, ...facts].filter(Boolean).map((part, index) => (
                        <span
                            key={`${index}-${part}`}
                            className={index === 0 && label ? 'TodayRow__label' : undefined}
                            data-tone={index === 0 && label ? tone : undefined}
                        >
                            {index === 0 ? part : ` · ${part}`}
                        </span>
                    ))}
                </p>
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
