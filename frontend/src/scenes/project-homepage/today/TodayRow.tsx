import { Collapsible } from '@base-ui/react/collapsible'
import { type ReactNode, useState } from 'react'

import { IconArrowRight, IconChevronDown } from '@posthog/icons'
import { IconStack, IconStackItem } from '@posthog/quill'

import type { TodayRowIcon } from './todayRowIcons'
import { TodayRowMeta } from './TodayRowMeta'
import { TodayRowTitle } from './TodayRowTitle'

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
    const expanded = !!expansion?.expanded
    const [reasonTruncated, setReasonTruncated] = useState(false)
    const content = (
        <>
            <IconStack className="TodayRow__icons">
                <IconStackItem color={icon.color}>{icon.glyph}</IconStackItem>
            </IconStack>
            <div className="min-w-0">
                <TodayRowTitle
                    title={title}
                    to={to}
                    onOpen={onOpen}
                    expandable={!!expansion}
                    reason={reason}
                    reasonTruncated={reasonTruncated}
                    reportId={reportId}
                    dataAttr={dataAttr}
                />
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
