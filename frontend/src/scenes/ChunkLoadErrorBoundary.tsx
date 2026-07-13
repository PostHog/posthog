import { Component, createContext, type ReactNode } from 'react'

import { isChunkLoadError } from 'lib/utils/isChunkLoadError'

const RELOAD_GUARD_KEY = 'posthog-chunk-reload-at'
const RELOAD_GUARD_WINDOW_MS = 20_000

/**
 * True wherever a ChunkLoadErrorBoundary is mounted above, i.e. a rethrown chunk-load error
 * gets recovered with a one-time reload instead of escaping to the React root. Nested error
 * boundaries (layout/ErrorBoundary) check this before rethrowing chunk-load errors upward.
 */
export const ChunkLoadRecoveryContext = createContext(false)

interface State {
    error: unknown
    surface: boolean
}

/**
 * Catches chunk-load failures from `React.lazy(() => import(...))` boundaries.
 * On a stale-deploy chunk-hash mismatch we reload once; if a reload was already
 * attempted in the last 20s we let the error bubble to the outer ErrorBoundary
 * rather than spinning forever. Non-chunk errors are re-thrown so the regular
 * error UI still renders.
 */
interface ChunkLoadErrorBoundaryProps {
    children: ReactNode
    reload?: () => void
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

    override render(): ReactNode {
        const { error, surface } = this.state
        if (error && (!isChunkLoadError(error) || surface)) {
            throw error
        }
        if (error && isChunkLoadError(error)) {
            return null
        }
        return <ChunkLoadRecoveryContext.Provider value={true}>{this.props.children}</ChunkLoadRecoveryContext.Provider>
    }
}
