import { Component, type ReactNode } from 'react'

import { isChunkLoadError, isLikelyStaleChunkRuntimeError } from 'lib/utils/isChunkLoadError'
import { reloadOnceForStaleChunk } from 'lib/utils/reloadOnceForStaleChunk'

interface State {
    error: unknown
    surface: boolean
}

interface ChunkLoadErrorBoundaryProps {
    children: ReactNode
    reload?: () => void
    /**
     * When true, also treat short minified `X is not a function` TypeErrors as stale-chunk
     * failures. Enable this on boundaries that wrap a `React.lazy(...)` import, where a
     * stale chunk can resolve to a degenerate module and React throws inside render before
     * any inner boundary mounts. Keep it off for general-purpose boundaries to avoid
     * masking real bugs as reload-and-pray.
     */
    matchStaleChunkRuntimeErrors?: boolean
}

/**
 * Catches chunk-load failures from `React.lazy(() => import(...))` boundaries.
 * On a stale-deploy chunk-hash mismatch we reload once; if a reload was already
 * attempted in the last 20s we let the error bubble to the outer ErrorBoundary
 * rather than spinning forever. Non-chunk errors are re-thrown so the regular
 * error UI still renders.
 */
export class ChunkLoadErrorBoundary extends Component<ChunkLoadErrorBoundaryProps, State> {
    override state: State = { error: null, surface: false }

    static getDerivedStateFromError(error: unknown): Partial<State> {
        return { error }
    }

    private isRecoverableError(error: unknown): boolean {
        if (isChunkLoadError(error)) {
            return true
        }
        if (this.props.matchStaleChunkRuntimeErrors && isLikelyStaleChunkRuntimeError(error)) {
            return true
        }
        return false
    }

    override componentDidCatch(error: unknown): void {
        if (!this.isRecoverableError(error)) {
            return
        }
        if (!reloadOnceForStaleChunk(this.props.reload)) {
            console.error('[ChunkLoadErrorBoundary] Recently reloaded; surfacing error instead of looping.')
            this.setState({ surface: true })
            return
        }
        console.warn('[ChunkLoadErrorBoundary] Chunk-load failure (likely stale deploy); reloading.')
    }

    override render(): ReactNode {
        const { error, surface } = this.state
        const recoverable = error != null && this.isRecoverableError(error)
        if (error && (!recoverable || surface)) {
            throw error
        }
        if (error && recoverable) {
            return null
        }
        return this.props.children
    }
}
