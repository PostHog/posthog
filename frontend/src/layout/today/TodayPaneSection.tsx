import { ReactNode } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

interface TodayPaneSectionProps {
    label: string
    open: boolean
    count: number
    onToggle: () => void
    actions?: JSX.Element | null
    divider?: boolean
    dataAttr: string
    children: ReactNode
}

export function TodayPaneSection({
    label,
    open,
    count,
    onToggle,
    actions,
    divider = false,
    dataAttr,
    children,
}: TodayPaneSectionProps): JSX.Element {
    const Caret = open ? IconChevronDown : IconChevronRight
    return (
        <section aria-label={label} className={cn('TodayPaneSection', divider && 'TodayPaneSection--divider')}>
            <div className="TodayPaneSection__header">
                <button
                    type="button"
                    className="TodayPaneSection__toggle Today__label"
                    aria-expanded={open}
                    data-attr={dataAttr}
                    onClick={onToggle}
                >
                    <span>{label}</span>
                    <Caret className="TodayPaneSection__caret" />
                    {!open && count > 0 && <span className="TodayPaneSection__count">{count}</span>}
                </button>
                {open && actions && <div className="TodayPaneSection__actions">{actions}</div>}
            </div>
            {open && <div className="TodayPaneSection__body">{children}</div>}
        </section>
    )
}
