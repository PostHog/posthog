import { ReactNode, RefCallback } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { MenuLabel, cn } from '@posthog/quill'

import { TodayPaneSectionResizeHandle } from './TodayPaneSectionResizeHandle'
import { TodaySectionResizer } from './useTodaySectionLayout'

export interface TodayPaneSectionProps {
    label: string
    /** Shows before the label, for a section whose source matters, such as the PostHog mark. */
    icon?: JSX.Element | null
    open: boolean
    count: number
    /** Whether the row count shows next to a collapsed label. */
    showCount?: boolean
    onToggle: () => void
    actions?: JSX.Element | null
    /** Replaces the label while set, for example with a search field. */
    heading?: JSX.Element | null
    divider?: boolean
    dataAttr: string
    height?: number
    animate?: boolean
    resizer?: TodaySectionResizer
    resizing?: boolean
    contentRef?: RefCallback<HTMLElement>
    children: ReactNode
}

export function TodayPaneSection({
    label,
    icon,
    open,
    count,
    showCount = true,
    onToggle,
    actions,
    heading,
    divider = false,
    dataAttr,
    height,
    animate = false,
    resizer,
    resizing = false,
    contentRef,
    children,
}: TodayPaneSectionProps): JSX.Element {
    const Caret = open ? IconChevronDown : IconChevronRight
    return (
        <section aria-label={label} className="flex shrink-0 flex-col">
            <div className={cn('relative flex h-7 shrink-0 items-center gap-1', divider && 'border-t border-border')}>
                {resizer && <TodayPaneSectionResizeHandle label={label} active={resizing} resizer={resizer} />}
                {heading ?? (
                    <MenuLabel
                        render={<button type="button" />}
                        aria-expanded={open}
                        data-attr={dataAttr}
                        onClick={onToggle}
                        className="flex min-w-0 flex-1 cursor-pointer items-center gap-1 rounded-sm py-1 text-left text-foreground/70 hover:text-foreground"
                    >
                        {icon && (
                            <span
                                className="flex size-3.5 shrink-0 items-center justify-center [&_svg]:size-3.5"
                                aria-hidden
                            >
                                {icon}
                            </span>
                        )}
                        <span>{label}</span>
                        <Caret className="size-3 shrink-0 opacity-60" />
                        {!open && showCount && count > 0 && (
                            <span className="ml-0.5 font-normal text-muted-foreground tabular-nums">{count}</span>
                        )}
                    </MenuLabel>
                )}
                {open && actions && <div className="flex shrink-0 items-center">{actions}</div>}
            </div>
            <div
                className={cn(
                    'min-h-0 shrink-0 overflow-hidden',
                    animate && 'transition-all duration-200 ease-out motion-reduce:transition-none'
                )}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ height: open ? (height ?? 'auto') : 0 }}
            >
                {open && (
                    <div className="scroll-mask-8 h-full scroll-py-8 overflow-y-auto">
                        <div ref={contentRef} className="flex flex-col gap-px pb-2">
                            {children}
                        </div>
                    </div>
                )}
            </div>
        </section>
    )
}
