import { ReactNode, RefCallback, useId } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { AutocompleteItem, Button, cn } from '@posthog/quill'

import { SidebarSectionResizeHandle } from './SidebarSectionResizeHandle'
import { SECTION_TOGGLE_ATTR } from './sidebarTreeKeys'
import { SidebarSectionResizer } from './types'

// The heading is a small button: it shows a hover and keyboard highlight like the rows, in the section label's type.
const TRIGGER_CLASS_NAME =
    'min-w-0 flex-1 text-xxs font-semibold uppercase tracking-[0.075em] text-muted-foreground hover:text-foreground ' +
    'data-highlighted:text-foreground data-highlighted:border-transparent data-highlighted:ring-0 [&>span]:gap-1 ' +
    // An open section is the usual state, so it does not take the expanded fill of a menu trigger.
    '[&[aria-expanded=true]:not(:hover,[data-highlighted])]:bg-transparent [&[aria-expanded=true]:not(:hover,[data-highlighted])]:text-muted-foreground'

export interface SidebarSectionProps {
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
    resizer?: SidebarSectionResizer
    resizing?: boolean
    contentRef?: RefCallback<HTMLElement>
    children: ReactNode
}

export function SidebarSection({
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
}: SidebarSectionProps): JSX.Element {
    const contentId = useId()
    const triggerProps = {
        'aria-expanded': open,
        'aria-controls': contentId,
        'data-attr': dataAttr,
        [SECTION_TOGGLE_ATTR]: '',
        onClick: onToggle,
    }
    const trigger = <Button size="sm" left className={TRIGGER_CLASS_NAME} />
    const triggerContent = (
        <>
            {icon && (
                <span className="flex size-3.5 shrink-0 items-center justify-center [&_svg]:size-3.5" aria-hidden>
                    {icon}
                </span>
            )}
            <span>{label}</span>
            <IconChevronRight className={cn('size-3 shrink-0 opacity-60', open && 'rotate-90')} />
            {!open && showCount && count > 0 && (
                <span className="ml-0.5 font-normal text-muted-foreground tabular-nums">{count}</span>
            )}
        </>
    )
    return (
        <section aria-label={label} className="flex shrink-0 flex-col">
            <div className={cn('relative flex h-7 shrink-0 items-center gap-1', divider && 'border-t border-border')}>
                {resizer && <SidebarSectionResizeHandle label={label} active={resizing} resizer={resizer} />}
                {heading ?? (
                    // The heading is a list option, so the arrow keys reach it with the rows.
                    <AutocompleteItem value={`section:${dataAttr}`} {...triggerProps} render={trigger}>
                        {triggerContent}
                    </AutocompleteItem>
                )}
                {open && actions && <div className="flex shrink-0 items-center">{actions}</div>}
            </div>
            <div
                id={contentId}
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
