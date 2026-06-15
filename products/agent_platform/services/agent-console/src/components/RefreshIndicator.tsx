/**
 * `<RefreshIndicator>` — single drop-in widget that owns auto-refresh
 * for a panel's data resource and exposes a manual refresh button.
 *
 * Pattern in a panel header:
 *
 *   const sessions = useResource(() => listSessions(...), [...])
 *   <PanelHeader>
 *     <RefreshIndicator resource={sessions} intervalMs={5000} />
 *   </PanelHeader>
 *
 * Renders a relative timestamp ("updated 5s ago") and a refresh
 * button that triggers the underlying resource's `reload()`. The
 * background timer pauses when the tab is hidden (see
 * `useAutoRefresh`).
 */

'use client'

import { RefreshCwIcon } from 'lucide-react'
import { useEffect, useState } from 'react'

import { useAutoRefresh } from '@/lib/useAutoRefresh'
import type { ResourceState } from '@/lib/useResource'

interface RefreshIndicatorProps<T> {
    resource: ResourceState<T>
    /** Background refresh interval, ms. Pass 0 to disable auto-refresh. */
    intervalMs?: number
    /** Disable the timer without removing the button. */
    paused?: boolean
    /** Optional label rendered before the timestamp. */
    label?: string
}

const DEFAULT_INTERVAL_MS = 10_000

export function RefreshIndicator<T>({
    resource,
    intervalMs = DEFAULT_INTERVAL_MS,
    paused = false,
    label,
}: RefreshIndicatorProps<T>): React.ReactElement {
    useAutoRefresh(resource, { intervalMs, paused })
    const timestamp = useRelativeTimestamp(resource.lastFetchedAt)

    return (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
            {label && <span>{label}</span>}
            <span aria-live="polite">{timestamp}</span>
            <button
                type="button"
                onClick={() => resource.reload()}
                disabled={resource.loading}
                aria-label="Refresh"
                title="Refresh"
                className="inline-flex h-6 w-6 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
            >
                <RefreshCwIcon className={`h-3.5 w-3.5 ${resource.loading ? 'animate-spin' : ''}`} />
            </button>
        </div>
    )
}

function useRelativeTimestamp(ts: number | null): string {
    const [now, setNow] = useState<number>(() => Date.now())
    useEffect(() => {
        if (ts === null) {
            return
        }
        // Re-render every second so the relative label stays fresh.
        const id = window.setInterval(() => setNow(Date.now()), 1000)
        return () => window.clearInterval(id)
    }, [ts])
    if (ts === null) {
        return 'loading…'
    }
    const seconds = Math.max(0, Math.round((now - ts) / 1000))
    if (seconds < 5) {
        return 'just now'
    }
    if (seconds < 60) {
        return `${seconds}s ago`
    }
    const minutes = Math.floor(seconds / 60)
    if (minutes < 60) {
        return `${minutes}m ago`
    }
    const hours = Math.floor(minutes / 60)
    return `${hours}h ago`
}
