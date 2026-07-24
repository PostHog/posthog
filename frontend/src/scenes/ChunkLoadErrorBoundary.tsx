import { Component, type ReactNode } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { isChunkLoadError } from 'lib/utils/isChunkLoadError'

const RELOAD_GUARD_KEY = 'posthog-chunk-reload-at'
const RELOAD_GUARD_WINDOW_MS = 20_000

interface State {
    error: unknown
    surface: boolean
}

/**
 * Catches chunk-load failures from `React.lazy(() => import(...))` boundaries.
 *
 * A stale-deploy chunk-hash mismatch (a tab opened before a deploy fetching a now-deleted chunk)
 * has two recoveries depending on where the boundary sits:
 *
 * - `autoReload` (boot boundary, before any user work exists): reload once to pull fresh assets.
 *   If a reload already happened in the last 20s we surface the error to the outer boundary rather
 *   than looping.
 * - default (in-app boundaries): show a non-blocking "refresh to update" prompt instead of yanking
 *   the page out from under active work (an open dashboard, an in-progress insight edit). The user
 *   refreshes when ready, so unsaved context isn't destroyed by a surprise full-page reload.
 *
 * Non-chunk errors are re-thrown so the regular error UI still renders.
 */
interface ChunkLoadErrorBoundaryProps {
    children: ReactNode
    /** Reload once automatically instead of prompting. Used by the boot boundary only. */
    autoReload?: boolean
    /** Test seam for the reload side effect. */
    reload?: () => void
}

function ChunkLoadRefreshPrompt({ onReload }: { onReload: () => void }): JSX.Element {
    return (
        <div className="flex items-center justify-center p-4" data-attr="chunk-load-refresh-prompt">
            <div className="flex flex-col items-center gap-2 rounded border bg-surface-primary p-6 text-center shadow-sm">
                <p className="m-0 font-semibold">A new version of PostHog is available</p>
                <p className="m-0 text-secondary">Refresh the page to load it. Your work so far isn't affected.</p>
                <LemonButton type="primary" onClick={onReload} className="mt-2">
                    Refresh
                </LemonButton>
            </div>
        </div>
    )
}

export class ChunkLoadErrorBoundary extends Component<ChunkLoadErrorBoundaryProps, State> {
    override state: State = { error: null, surface: false }

    static getDerivedStateFromError(error: unknown): Partial<State> {
        return { error }
    }

    override componentDidCatch(error: unknown): void {
        if (!isChunkLoadError(error) || !this.props.autoReload) {
            return
        }
        let lastReload = 0
        try {
            lastReload = Number(window.localStorage.getItem(RELOAD_GUARD_KEY) ?? 0)
        } catch {
            // localStorage may be unavailable (e.g. Safari private mode) - treat as no prior reload
        }
        if (lastReload && Date.now() - lastReload < RELOAD_GUARD_WINDOW_MS) {
            console.error('[ChunkLoadErrorBoundary] Recently reloaded; surfacing error instead of looping.')
            this.setState({ surface: true })
            return
        }
        console.warn('[ChunkLoadErrorBoundary] Chunk-load failure (likely stale deploy); reloading.')
        try {
            window.localStorage.setItem(RELOAD_GUARD_KEY, String(Date.now()))
        } catch {
            // localStorage may throw QuotaExceededError (Safari private mode, full storage).
            // Skip the guard and reload anyway - without the timestamp the worst case is
            // a reload loop, which only happens if the chunk itself keeps failing.
        }
        this.reload()
    }

    private reload = (): void => {
        if (this.props.reload) {
            this.props.reload()
        } else {
            window.location.reload()
        }
    }

    override render(): ReactNode {
        const { error, surface } = this.state
        if (error && (!isChunkLoadError(error) || surface)) {
            throw error
        }
        if (error && isChunkLoadError(error)) {
            // Auto-reload boundaries have already triggered a reload in componentDidCatch, so render
            // nothing until it lands. In-app boundaries show a prompt rather than reloading.
            return this.props.autoReload ? null : <ChunkLoadRefreshPrompt onReload={this.reload} />
        }
        return this.props.children
    }
}
