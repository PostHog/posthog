import { ReactNode, useState } from 'react'

import { IconChevronRight } from '@posthog/icons'

interface DetailSectionProps {
    icon: ReactNode
    title: string
    /** Metadata rendered immediately after the title, before the divider (e.g. a branch tag, info icon). */
    afterTitle?: ReactNode
    rightSlot?: ReactNode
    children: ReactNode
    /** When set, the header toggles the body open/closed. */
    collapsible?: boolean
    /** Start collapsed (only honoured when `collapsible`). */
    defaultCollapsed?: boolean
}

/**
 * Content section with an icon + title header and a spanning divider, used throughout the report
 * detail (Summary, Files changed, Reviewers, Runs, Activity). Optionally collapsible — the header
 * becomes a toggle while `rightSlot` stays outside it so its own controls remain clickable.
 */
export function DetailSection({
    icon,
    title,
    afterTitle,
    rightSlot,
    children,
    collapsible = false,
    defaultCollapsed = false,
}: DetailSectionProps): JSX.Element {
    const [collapsed, setCollapsed] = useState(defaultCollapsed)
    const open = !collapsible || !collapsed

    const heading = (
        <div className="flex items-center gap-2 min-w-0">
            <span className="flex shrink-0 items-center text-secondary [&_svg]:size-[0.9375rem]">{icon}</span>
            <span className="truncate font-semibold text-sm text-primary tracking-tight">{title}</span>
        </div>
    )

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center gap-3 min-w-0 select-none">
                <div className="flex items-center gap-2 min-w-0">
                    {collapsible ? (
                        <button
                            type="button"
                            aria-expanded={open}
                            onClick={() => setCollapsed((c) => !c)}
                            className="flex items-center gap-1.5 min-w-0 rounded text-left transition-colors hover:text-primary"
                        >
                            <IconChevronRight
                                className={`size-3 shrink-0 text-tertiary transition-transform ${open ? 'rotate-90' : ''}`}
                            />
                            {heading}
                        </button>
                    ) : (
                        heading
                    )}
                    {afterTitle && <div className="shrink-0">{afterTitle}</div>}
                </div>
                <div className="h-px min-w-4 flex-1 bg-border-light" />
                {rightSlot && <div className="shrink-0">{rightSlot}</div>}
            </div>
            {open && <div>{children}</div>}
        </div>
    )
}
