import clsx from 'clsx'
import React from 'react'

import { IconMinus, IconPlusSmall } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

/** Text wrapper for a tool card's header label — the elegant ToolRow type ramp. */
export function ToolTitle({ children }: { children: React.ReactNode }): JSX.Element {
    return <span className="text-[13px] text-secondary min-w-0 truncate">{children}</span>
}

/** Dim `(Failed)` / `(Cancelled)` trailing marker; renders nothing in the happy path. */
export function StatusIndicators({
    isFailed,
    wasCancelled,
}: {
    isFailed: boolean
    wasCancelled: boolean
}): JSX.Element | null {
    if (isFailed) {
        return <span className="text-[13px] text-muted shrink-0">(Failed)</span>
    }
    if (wasCancelled) {
        return <span className="text-[13px] text-muted shrink-0">(Cancelled)</span>
    }
    return null
}

/** The tool icon, swapped for a spinner while the call is in flight. */
export function LoadingIcon({ icon, isLoading }: { icon: React.ReactNode; isLoading: boolean }): JSX.Element {
    return (
        <span className="flex items-center justify-center size-3.5 shrink-0 text-muted [&_svg]:size-3.5">
            {isLoading ? <Spinner className="size-3.5" /> : icon}
        </span>
    )
}

/**
 * Leading icon for a collapsible row: the tool icon by default, a spinner while loading, and a
 * plus/minus affordance on row hover (the parent supplies `group/toolrow`). Mirrors the agent UI's
 * expand glyph without a separate chevron column.
 */
export function ExpandableIcon({
    icon,
    isLoading,
    isExpanded,
}: {
    icon: React.ReactNode
    isLoading: boolean
    isExpanded: boolean
}): JSX.Element {
    if (isLoading) {
        return (
            <span className="flex items-center justify-center size-3.5 shrink-0">
                <Spinner className="size-3.5" />
            </span>
        )
    }
    return (
        <span className="relative flex items-center justify-center size-3.5 shrink-0 text-muted [&_svg]:size-3.5">
            <span className="inline-flex transition-opacity group-hover/toolrow:opacity-0">{icon}</span>
            <span className="absolute inset-0 inline-flex items-center justify-center opacity-0 transition-opacity group-hover/toolrow:opacity-100">
                {isExpanded ? <IconMinus /> : <IconPlusSmall />}
            </span>
        </span>
    )
}

/** Monospace, scrollable output block for terminal / search / fetch bodies. */
export function ToolContentPre({
    children,
    className,
}: {
    children: React.ReactNode
    className?: string
}): JSX.Element {
    return (
        <pre
            className={clsx(
                'm-0 font-mono text-[13px] leading-relaxed text-secondary whitespace-pre-wrap break-all',
                'max-h-64 overflow-auto',
                className
            )}
        >
            {children}
        </pre>
    )
}
