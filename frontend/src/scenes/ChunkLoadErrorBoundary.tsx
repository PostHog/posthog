import { Component, type ReactNode } from 'react'

import { registerChunkReloadAttempt } from 'lib/utils/chunkReloadGuard'
import { isChunkLoadError } from 'lib/utils/isChunkLoadError'

interface State {
    error: unknown
    surface: boolean
}

/**
 * Catches chunk-load failures from `React.lazy(() => import(...))` boundaries.
 * On a stale-deploy chunk-hash mismatch we reload once; if we have already reloaded
 * in this run we let the error bubble to the outer ErrorBoundary rather than spinning
 * forever. Non-chunk errors are re-thrown so the regular error UI still renders.
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
        if (!registerChunkReloadAttempt(Date.now()).shouldReload) {
            console.error('[ChunkLoadErrorBoundary] Already reloaded; surfacing error instead of looping.')
            this.setState({ surface: true })
            return
        }
        console.warn('[ChunkLoadErrorBoundary] Chunk-load failure (likely stale deploy); reloading.')
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
        return this.props.children
    }
}
