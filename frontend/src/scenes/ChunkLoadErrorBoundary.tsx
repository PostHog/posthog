import { Component, type ReactNode } from 'react'

const RELOAD_GUARD_KEY = 'posthog-chunk-reload-at'
const RELOAD_GUARD_WINDOW_MS = 20_000

function isChunkLoadError(error: unknown): boolean {
    if (!error || typeof error !== 'object') {
        return false
    }
    const err = error as { name?: string; message?: string }
    return (
        err.name === 'ChunkLoadError' ||
        (typeof err.message === 'string' && err.message.includes('Failed to fetch dynamically imported module'))
    )
}

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
export class ChunkLoadErrorBoundary extends Component<{ children: ReactNode }, State> {
    override state: State = { error: null, surface: false }

    static getDerivedStateFromError(error: unknown): Partial<State> {
        return { error }
    }

    override componentDidCatch(error: unknown): void {
        if (!isChunkLoadError(error)) {
            return
        }
        const lastReload = Number(window.localStorage.getItem(RELOAD_GUARD_KEY) ?? 0)
        if (lastReload && Date.now() - lastReload < RELOAD_GUARD_WINDOW_MS) {
            console.error('[ChunkLoadErrorBoundary] Recently reloaded; surfacing error instead of looping.')
            this.setState({ surface: true })
            return
        }
        console.warn('[ChunkLoadErrorBoundary] Chunk-load failure (likely stale deploy); reloading.')
        window.localStorage.setItem(RELOAD_GUARD_KEY, String(Date.now()))
        window.location.reload()
    }

    override render(): ReactNode {
        const { error, surface } = this.state
        if (error && (!isChunkLoadError(error) || surface)) {
            throw error
        }
        if (error && isChunkLoadError(error)) {
            return null
        }
        return this.props.children
    }
}
