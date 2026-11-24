import React from 'react'

import { isChunkLoadError } from 'lib/utils/isChunkLoadError'

import { reportBootFailure } from './reportBootFailure'

interface RootErrorBoundaryState {
    hasError: boolean
    error: unknown
}

/**
 * Dependency-free last-resort boundary around the whole app. Everything inside the App chunk
 * (posthog-js, the full ErrorBoundary, all UI) can fail to load or crash on boot — this
 * boundary is what remains, so it reports the failure itself and offers a manual reload.
 * Stale-deploy chunk errors auto-reload once via the ChunkLoadErrorBoundary nested inside it
 * (see index.tsx); only errors that survive that recovery surface here.
 */
export class RootErrorBoundary extends React.Component<{ children: React.ReactNode }, RootErrorBoundaryState> {
    override state: RootErrorBoundaryState = { hasError: false, error: null }

    static getDerivedStateFromError(error: unknown): RootErrorBoundaryState {
        return { hasError: true, error }
    }

    override componentDidCatch(error: unknown, errorInfo: React.ErrorInfo): void {
        console.error('[PostHog] App failed to start:', error, errorInfo.componentStack)
        reportBootFailure(error)
    }

    override render(): React.ReactNode {
        if (this.state.hasError) {
            return (
                <div className="Preloader" role="alert">
                    <div>
                        {isChunkLoadError(this.state.error)
                            ? 'PostHog failed to load. '
                            : 'PostHog crashed while starting. '}
                        <button onClick={() => window.location.reload()}>Reload the page</button> to try again.
                    </div>
                </div>
            )
        }
        return this.props.children
    }
}
