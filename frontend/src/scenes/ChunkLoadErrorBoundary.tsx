import { Component, type ReactNode } from 'react'

import { isChunkLoadError } from 'lib/utils/isChunkLoadError'

const RELOAD_GUARD_KEY = 'posthog-chunk-reload-at'
const RELOAD_GUARD_WINDOW_MS = 20_000

interface State {
    error: unknown
    surface: boolean
}

/**
 * Catches chunk-load failures from `React.lazy(() => import(...))` boundaries.
 * On a stale-deploy chunk-hash mismatch we reload once; if a reload was already
 * attempted in the last 20s we render `fallback` when given, or else let the error
 * bubble to the outer ErrorBoundary rather than spinning forever. Non-chunk errors
 * are re-thrown so the regular error UI still renders.
 */
interface ChunkLoadErrorBoundaryProps {
    children: ReactNode
    reload?: () => void
    /**
     * `retry` clears the caught error and re-renders `children`, which re-requests the
     * missing chunk. State held outside this subtree survives that, so a fallback that
     * offers `retry` lets the person carry on rather than start over.
     */
    fallback?: (error: unknown, retry: () => void) => ReactNode
    /**
     * Set when the subtree holds state the person has typed and not yet saved, so a
     * scripted reload would discard it. The boundary then renders `fallback` straight
     * away and leaves the reload to the person.
     */
    holdsUnsavedWork?: boolean
}

export class ChunkLoadErrorBoundary extends Component<ChunkLoadErrorBoundaryProps, State> {
    override state: State = { error: null, surface: false }

    static getDerivedStateFromError(error: unknown): Partial<State> {
        return { error }
    }

    override componentDidCatch(error: unknown): void {
        if (!isChunkLoadError(error)) {
            return
        }
        // Reloading cannot recover this subtree: its own chunk already loaded, so only a chunk it
        // asked for later is missing. It would just discard what the person has typed since.
        if (this.props.holdsUnsavedWork && this.props.fallback) {
            this.setState({ surface: true })
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
        if (this.props.reload) {
            this.props.reload()
        } else {
            window.location.reload()
        }
    }

    private retry = (): void => {
        this.setState({ error: null, surface: false })
    }

    override render(): ReactNode {
        const { error, surface } = this.state
        if (error && surface && isChunkLoadError(error) && this.props.fallback) {
            return this.props.fallback(error, this.retry)
        }
        if (error && (!isChunkLoadError(error) || surface)) {
            throw error
        }
        if (error && isChunkLoadError(error)) {
            return null
        }
        return this.props.children
    }
}
