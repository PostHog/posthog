import clsx from 'clsx'

import { IconCheck, IconChevronRight, IconX } from '@posthog/icons'

import type { ToolInvocationStatus } from '../types/sandboxStreamTypes'

/**
 * Wraps content in a shimmering gradient while a tool call is in flight. Text shimmers the
 * gradient through the glyphs; non-text content (icons) shimmers opacity instead. Extracted
 * from `AssistantActionComponent` so the sandbox tool-card renderers share the same status
 * visuals (03_RICH_UI.md §2.4 / §6.2).
 */
export function ShimmeringContent({ children }: { children: React.ReactNode }): JSX.Element {
    const isTextContent = typeof children === 'string'

    if (isTextContent) {
        return (
            <span
                className="bg-clip-text text-transparent"
                style={{
                    backgroundImage:
                        'linear-gradient(in oklch 90deg, var(--text-3000), var(--muted-3000), var(--trace-3000), var(--muted-3000), var(--text-3000))',
                    backgroundSize: '200% 100%',
                    animation: 'shimmer 3s linear infinite',
                }}
            >
                {children}
            </span>
        )
    }

    return (
        <span
            className="inline-flex min-w-0 max-w-full"
            style={{
                animation: 'shimmer-opacity 3s linear infinite',
            }}
        >
            {children}
        </span>
    )
}

export interface ToolCardHeaderProps {
    /** Tool-call lifecycle status; drives the shimmer / check / red-X status visuals. */
    status: ToolInvocationStatus
    /** Leading icon for the tool — shimmers while `in_progress`. */
    icon?: React.ReactNode
    /** One-line header label (the tool's display name / title). */
    label: React.ReactNode
    /** When set, renders an expand/collapse chevron that rotates while `expanded`. */
    onToggle?: () => void
    expanded?: boolean
    /** Suppress the terminal check / red-X glyph (e.g. when a custom widget shows status). */
    showCompletionIcon?: boolean
}

/**
 * Reusable tool-call header row with the §2.4 status convention: shimmering header + icon while
 * `in_progress`, a green check on `completed`, a red X on `failed`, muted text on `pending`/`failed`.
 * The sandbox MCP tool-card renderers reuse this so their status visuals match the LangGraph
 * `AssistantActionComponent` header they were extracted from. LangGraph rendering is untouched —
 * this is additive and only consumed by the sandbox tool cards.
 */
export function ToolCardHeader({
    status,
    icon,
    label,
    onToggle,
    expanded = false,
    showCompletionIcon = true,
}: ToolCardHeaderProps): JSX.Element {
    const isPending = status === 'pending'
    const isInProgress = status === 'in_progress'
    const isCompleted = status === 'completed'
    const isFailed = status === 'failed'

    return (
        <div
            className={clsx(
                'flex select-none min-w-0 items-center gap-1',
                (isPending || isFailed) && 'text-muted',
                !isInProgress && !isPending && !isFailed && 'text-default',
                onToggle ? 'cursor-pointer' : 'cursor-default'
            )}
            onClick={onToggle}
            aria-label={onToggle ? (expanded ? 'Collapse result' : 'Expand result') : undefined}
        >
            {icon && (
                <div className="flex items-center justify-center size-5 flex-shrink-0">
                    {isInProgress ? (
                        <ShimmeringContent>{icon}</ShimmeringContent>
                    ) : (
                        <span className={clsx('inline-flex', isInProgress && 'text-muted')}>{icon}</span>
                    )}
                </div>
            )}
            <div className="min-w-0 flex-1 truncate font-medium">
                {isInProgress ? <ShimmeringContent>{label}</ShimmeringContent> : label}
            </div>
            {onToggle && (
                <button
                    type="button"
                    className="inline-flex items-center hover:opacity-70 transition-opacity flex-shrink-0 cursor-pointer"
                >
                    <span className={clsx('transform transition-transform', expanded && 'rotate-90')}>
                        <IconChevronRight />
                    </span>
                </button>
            )}
            {isCompleted && showCompletionIcon && <IconCheck className="text-success size-3 flex-shrink-0" />}
            {isFailed && showCompletionIcon && <IconX className="text-danger size-3 flex-shrink-0" />}
        </div>
    )
}
