import { Component, type ReactNode } from 'react'

import { isChunkLoadError } from 'lib/utils/isChunkLoadError'
import { isStableChunkBuild, reloadAfterChunkLoadError } from 'lib/utils/stableChunks'

const RELOAD_GUARD_KEY = 'posthog-chunk-reload-at'
const RELOAD_GUARD_WINDOW_MS = 20_000

interface State {
    /** Separate from `error` because a component can throw `null` or `undefined`. */
    hasError: boolean
    error: unknown
    surface: boolean
}

/**
 * Catches chunk-load failures from `React.lazy(() => import(...))` boundaries.
 * On a stale-deploy chunk-hash mismatch we reload once; if a reload was already
 * attempted in the last 20s we render `fallback` when given, or else let the error
 * bubble to the outer ErrorBoundary rather than spinning forever. On the stable chunk
 * build we always reload on the default build, which cannot loop. Non-chunk errors
 * are re-thrown so the regular error UI still renders.
 */
interface ChunkLoadErrorBoundaryProps {
    children: ReactNode
    reload?: () => void
    fallback?: (error: unknown) => ReactNode
}

export class ChunkLoadErrorBoundary extends Component<ChunkLoadErrorBoundaryProps, State> {
    override state: State = { hasError: false, error: null, surface: false }

    static getDerivedStateFromError(error: unknown): Partial<State> {
        return { hasError: true, error }
    }

    override componentDidCatch(error: unknown): void {
        if (!isChunkLoadError(error)) {
            return
        }
        let lastReload = 0
        try {
            lastReload = Number(window.localStorage.getItem(RELOAD_GUARD_KEY) ?? 0)
        } catch {
            // localStorage may be unavailable (e.g. Safari private mode) - treat as no prior reload
        }
        if (lastReload && Date.now() - lastReload < RELOAD_GUARD_WINDOW_MS && !isStableChunkBuild()) {
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
            reloadAfterChunkLoadError(error)
        }
    }

    override render(): ReactNode {
        const { hasError, error, surface } = this.state
        if (!hasError) {
            return this.props.children
        }
        if (surface && isChunkLoadError(error) && this.props.fallback) {
            return this.props.fallback(error)
        }
        if (!isChunkLoadError(error) || surface) {
            throw error
        }
        return null
    }
}
