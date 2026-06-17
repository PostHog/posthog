import { IconCheck, IconWarning, IconX } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'

import type { ThreadItem } from '../types/sandboxStreamTypes'

/** Inline `_posthog/status` item — a spinner while compacting, a generic status line otherwise. */
export function SandboxStatusItem({ item }: { item: ThreadItem }): JSX.Element {
    const isCompacting = item.status === 'compacting' && !item.isComplete
    return (
        <div className="flex items-center justify-center gap-2 py-1 text-xs text-muted">
            {isCompacting ? (
                <>
                    <Spinner className="size-3" />
                    <span>Compacting conversation history…</span>
                </>
            ) : (
                <span>Status: {item.status}</span>
            )}
        </div>
    )
}

/** Inline `_posthog/compact_boundary` item — the post-compaction rule. */
export function SandboxCompactBoundaryItem({ item }: { item: ThreadItem }): JSX.Element {
    return (
        <div className="flex items-center gap-2 py-1 text-xs text-muted">
            <div className="h-px grow bg-border" />
            <span className="shrink-0">
                Conversation compacted
                {item.trigger ? ` (${item.trigger})` : ''}
                {typeof item.preTokens === 'number'
                    ? ` · ~${humanFriendlyNumber(item.preTokens)} tokens summarized`
                    : ''}
            </span>
            <div className="h-px grow bg-border" />
        </div>
    )
}

/** Inline `_posthog/task_notification` item — a colored rule by status (completed/failed/stopped). */
export function SandboxTaskNotificationItem({ item }: { item: ThreadItem }): JSX.Element {
    const colorClass =
        item.status === 'completed' ? 'text-success' : item.status === 'failed' ? 'text-danger' : 'text-warning'
    const icon =
        item.status === 'completed' ? (
            <IconCheck className="size-3" />
        ) : item.status === 'failed' ? (
            <IconX className="size-3" />
        ) : (
            <IconWarning className="size-3" />
        )
    return (
        <div className={cn('flex items-center justify-center gap-1.5 py-1 text-xs', colorClass)}>
            {icon}
            <span>{item.summary || `Task ${item.status}`}</span>
        </div>
    )
}
