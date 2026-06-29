import { ReactNode, useState } from 'react'

import { IconChevronRight } from '@posthog/icons'

interface DetailSectionProps {
    icon: ReactNode
    title: string
    rightSlot?: ReactNode
    children: ReactNode
}

/** Prominent content section with a spanning divider, used for the main column (Summary, Evidence). */
export function DetailSection({ icon, title, rightSlot, children }: DetailSectionProps): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center gap-3 min-w-0 cursor-default select-none">
                <div className="flex items-center gap-2 min-w-0">
                    <span className="flex shrink-0 items-center text-secondary [&_svg]:size-[0.9375rem]">{icon}</span>
                    <span className="truncate font-semibold text-sm text-primary tracking-tight">{title}</span>
                </div>
                <div className="h-px min-w-4 flex-1 bg-border-light" />
                {rightSlot && <div className="shrink-0">{rightSlot}</div>}
            </div>
            <div>{children}</div>
        </div>
    )
}

interface RightColumnSectionProps {
    icon: ReactNode
    title: string
    rightSlot?: ReactNode
    children: ReactNode
    /** When set, the header toggles the body open/closed. */
    collapsible?: boolean
    /** Start collapsed (only honoured when `collapsible`). */
    defaultCollapsed?: boolean
}

/**
 * Slim caption header used by sections in the detail-view right column (Runs, Reviewers).
 * Lighter than `DetailSection` so the side column reads as supporting detail. Optionally
 * collapsible — the header becomes a toggle while `rightSlot` stays outside it so its own
 * controls remain clickable.
 */
export function RightColumnSection({
    icon,
    title,
    rightSlot,
    children,
    collapsible = false,
    defaultCollapsed = false,
}: RightColumnSectionProps): JSX.Element {
    const [collapsed, setCollapsed] = useState(defaultCollapsed)
    const open = !collapsible || !collapsed

    const caption = (
        <>
            <span className="flex shrink-0 items-center [&_svg]:size-3">{icon}</span>
            <span className="font-medium text-[0.6875rem] uppercase tracking-wider">{title}</span>
        </>
    )

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2 select-none text-tertiary">
                {collapsible ? (
                    <button
                        type="button"
                        aria-expanded={open}
                        onClick={() => setCollapsed((c) => !c)}
                        className="flex items-center gap-2 rounded text-left transition-colors hover:text-secondary"
                    >
                        <IconChevronRight
                            className={`size-3 shrink-0 transition-transform ${open ? 'rotate-90' : ''}`}
                        />
                        {caption}
                    </button>
                ) : (
                    <div className="flex items-center gap-2 cursor-default">{caption}</div>
                )}
                {rightSlot && <div className="shrink-0">{rightSlot}</div>}
            </div>
            {open && <div>{children}</div>}
        </div>
    )
}
