import { Component, type ReactNode } from 'react'

import { markChunkFailureReload, reloadedForChunkFailureRecently } from 'lib/utils/chunkReloadGuard'
import { isChunkLoadError } from 'lib/utils/isChunkLoadError'

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
    fallback?: (error: unknown) => ReactNode
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
        if (reloadedForChunkFailureRecently()) {
            console.error('[ChunkLoadErrorBoundary] Recently reloaded; surfacing error instead of looping.')
            this.setState({ surface: true })
            return
        }
        console.warn('[ChunkLoadErrorBoundary] Chunk-load failure (likely stale deploy); reloading.')
        // The chunk already failed and one reload is the usual recovery from a stale deploy, so
        // reload even when the stamp does not persist.
        markChunkFailureReload()
        if (this.props.reload) {
            this.props.reload()
        } else {
            window.location.reload()
        }
    }

    override render(): ReactNode {
        const { error, surface } = this.state
        if (error && surface && isChunkLoadError(error) && this.props.fallback) {
            return this.props.fallback(error)
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
