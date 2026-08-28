import React from 'react'

import { isChunkLoadError } from 'lib/utils/isChunkLoadError'

/**
 * Report a boot failure straight to the capture API. posthog-js lives inside the App chunk —
 * the very chunk this boundary guards — so when boot fails there is no SDK to report through,
 * and without this beacon a broken deploy would be invisible to error tracking.
 * Fire-and-forget: reporting must never make a boot failure worse.
 */
function reportBootFailure(error: unknown): void {
    try {
        const apiKey = window.JS_POSTHOG_API_KEY
        if (!apiKey) {
            return // capture is opted out for this instance
        }
        const host = window.JS_POSTHOG_HOST || window.location.origin
        let distinctId: string | undefined
        try {
            // posthog-js persistence — absent on a first visit or under cookie-only persistence
            distinctId = JSON.parse(window.localStorage.getItem(`ph_${apiKey}_posthog`) || '{}').distinct_id
        } catch {
            // storage unavailable or corrupt — report anonymously
        }
        const err = error instanceof Error ? error : new Error(String(error))
        const payload = JSON.stringify({
            api_key: apiKey,
            event: '$exception',
            distinct_id: distinctId || `boot-failure-${Date.now()}`,
            properties: {
                // Personless event: don't create person profiles from anonymous boot beacons
                $process_person_profile: false,
                $current_url: window.location.href,
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
            },
        })
        // A string body goes out as text/plain: CORS-safelisted (no preflight) and accepted by
        // the capture endpoints. sendBeacon delivery survives the page unloading under a reload.
        const url = `${host}/e/`
        if (!(typeof navigator.sendBeacon === 'function' && navigator.sendBeacon(url, payload))) {
            void fetch(url, { method: 'POST', body: payload, keepalive: true }).catch(() => {})
        }
    } catch {
        // best-effort only
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
