import React from 'react'

import { captureViaBeacon } from 'lib/utils/captureViaBeacon'
import { isChunkLoadError } from 'lib/utils/isChunkLoadError'

/**
 * Report a boot failure straight to the capture API. posthog-js lives inside the App chunk —
 * the very chunk this boundary guards — so when boot fails there is no SDK to report through,
 * and without this beacon a broken deploy would be invisible to error tracking.
 */
function reportBootFailure(error: unknown): void {
    try {
        const err = error instanceof Error ? error : new Error(String(error))
        captureViaBeacon('$exception', {
            // Personless event: don't create person profiles from anonymous boot beacons
            $process_person_profile: false,
            $exception_level: 'fatal',
            $exception_list: [
                {
                    type: err.name || 'Error',
                    value: err.message,
                    mechanism: { handled: true, synthetic: false },
                },
            ],
            stack: err.stack,
            chunk_load_error: isChunkLoadError(error),
        })
    } catch {
        // A thrown value can resist stringification, and no boundary sits above this one to
        // catch a second failure, so the user would get a blank page instead of the panel.
    }
}

interface RootErrorBoundaryState {
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
    override state: RootErrorBoundaryState = { error: null }

    static getDerivedStateFromError(error: unknown): RootErrorBoundaryState {
        return { error }
    }

    override componentDidCatch(error: unknown, errorInfo: React.ErrorInfo): void {
        console.error('[PostHog] App failed to start:', error, errorInfo.componentStack)
        reportBootFailure(error)
    }

    override render(): React.ReactNode {
        if (this.state.error) {
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
