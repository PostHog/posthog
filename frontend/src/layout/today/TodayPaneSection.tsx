import { ReactNode, RefCallback } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { TodayPaneSectionResizeHandle } from './TodayPaneSectionResizeHandle'
import { TodaySectionResizer } from './useTodaySectionLayout'

export interface TodayPaneSectionProps {
    label: string
    open: boolean
    count: number
    onToggle: () => void
    actions?: JSX.Element | null
    divider?: boolean
    dataAttr: string
    height: number
    animate: boolean
    resizer?: TodaySectionResizer
    resizing?: boolean
    contentRef: RefCallback<HTMLElement>
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
    height,
    animate,
    resizer,
    resizing = false,
    contentRef,
    children,
}: TodayPaneSectionProps): JSX.Element {
    const Caret = open ? IconChevronDown : IconChevronRight
    return (
        <section aria-label={label} className={cn('TodayPaneSection', divider && 'TodayPaneSection--divider')}>
            <div className="TodayPaneSection__header">
                {resizer && <TodayPaneSectionResizeHandle label={label} active={resizing} resizer={resizer} />}
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
            <div
                className={cn('TodayPaneSection__viewport', animate && 'TodayPaneSection__viewport--animate')}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ height: open ? height : 0 }}
            >
                {open && (
                    <div className="TodayPaneSection__scroll">
                        <div ref={contentRef} className="TodayPaneSection__body">
                            {children}
                        </div>
                    </div>
                )}
            </div>
        </section>
    )
}
