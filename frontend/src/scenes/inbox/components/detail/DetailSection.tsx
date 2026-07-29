import { ReactNode, useState } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

interface DetailSectionProps {
    icon: ReactNode
    title: string
    /** Metadata rendered immediately after the title, before the divider (e.g. a branch tag, info icon). */
    afterTitle?: ReactNode
    /**
     * Non-interactive summary rendered at the end of the header row, after the divider (e.g. a
     * comment count). Part of the toggle when the section is collapsible — use `rightSlot` for
     * anything with its own click behavior.
     */
    meta?: ReactNode
    /** Interactive controls rendered outside the collapse toggle so they stay independently clickable. */
    rightSlot?: ReactNode
    children: ReactNode
    /** When set, the header toggles the body open/closed. */
    collapsible?: boolean
    /** Start collapsed (only honoured when `collapsible`). */
    defaultCollapsed?: boolean
}

/**
 * Content section with an icon + title header and a spanning divider, used throughout the report
 * detail (Summary, Files changed, Reviewers, Runs, Activity). Optionally collapsible — the whole
 * header row becomes a tertiary button toggle (expand/collapse icon at the row's end), while
 * `rightSlot` stays outside it so its own controls remain clickable. Both variants render the
 * same header row, so geometry is identical regardless of expandability.
 */
export function DetailSection({
    icon,
    title,
    afterTitle,
    meta,
    rightSlot,
    children,
    collapsible = false,
    defaultCollapsed = false,
}: DetailSectionProps): JSX.Element {
    const [collapsed, setCollapsed] = useState(defaultCollapsed)
    const open = !collapsible || !collapsed

    const headerRow = (
        <div className="flex flex-1 items-center gap-3 min-w-0">
            <div className="flex items-center gap-2 min-w-0">
                <span className="flex shrink-0 items-center text-secondary [&_svg]:size-[0.9375rem]">{icon}</span>
                <span className="truncate font-semibold text-sm text-primary tracking-tight">{title}</span>
                {afterTitle && <div className="shrink-0">{afterTitle}</div>}
            </div>
            <div className="h-px min-w-4 flex-1 bg-border-light" />
            {meta && <div className="shrink-0">{meta}</div>}
        </div>
    )

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center gap-3 min-w-0 select-none">
                {collapsible ? (
                    // The button keeps its natural small padding so the hover state wraps the row
                    // with a little air; `-ml-2` (= the small button's 0.5rem left padding) pulls the
                    // icon back onto the content column so it aligns with static section headers and
                    // the section bodies below.
                    <LemonButton
                        type="tertiary"
                        size="small"
                        fullWidth
                        onClick={() => setCollapsed((c) => !c)}
                        aria-expanded={open}
                        sideIcon={open ? <IconCollapse /> : <IconExpand />}
                        // `-my-px` trims the small button's extra height so its baseline matches the
                        // shorter static (non-button) headers.
                        className="min-w-0 flex-1 -ml-2 -my-px"
                    >
                        {headerRow}
                    </LemonButton>
                ) : (
                    // Match the collapsible button's vertical padding so every section header sits on
                    // the same baseline whether or not it collapses.
                    <div className="flex flex-1 items-center min-w-0 py-1">{headerRow}</div>
                )}
                {rightSlot && <div className="shrink-0">{rightSlot}</div>}
            </div>
            {open && <div>{children}</div>}
        </div>
    )
}
