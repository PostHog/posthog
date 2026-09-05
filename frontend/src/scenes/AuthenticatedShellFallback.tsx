import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { markChunkFailureReload, reloadedForChunkFailureRecently } from 'lib/utils/chunkReloadGuard'

// After this long the shell is almost certainly stuck (a stale-deploy chunk that
// never resolves), so reload once, or explain the wait and offer a reload.
const RETRY_PROMPT_DELAY_MS = 8000

/**
 * Suspense fallback for the authenticated shell chunk. It shows a spinner, then reloads the
 * page once the load is clearly stuck. A chunk that rejects already recovers through
 * `retryImport` and `ChunkLoadErrorBoundary`; a chunk that only hangs reaches neither, so
 * without this the person waits on a dead screen. The reload shares the boundary's guard,
 * which stops a chunk that keeps failing from reloading in a loop. When the guard blocks the
 * reload, the fallback explains the wait and offers a manual reload instead.
 *
 * `showSpinner` comes from `appLogic.showingDelayedSpinner`, which starts its delay
 * at app boot. The boot spinner can therefore be on screen before this fallback
 * mounts. A second delay timed from mount would hide the spinner again and blank
 * the screen between the two.
 */
export function AuthenticatedShellFallback({ showSpinner }: { showSpinner: boolean }): JSX.Element {
    const [showRetryPrompt, setShowRetryPrompt] = useState(false)

    useEffect(() => {
        const retryTimer = window.setTimeout(() => {
            const autoReload = !reloadedForChunkFailureRecently()
            // sendBeacon survives the page unloading under the reload below.
            posthog.capture('app shell load stalled', { auto_reloaded: autoReload }, { transport: 'sendBeacon' })
            if (autoReload) {
                markChunkFailureReload()
                window.location.reload()
                return
            }
            setShowRetryPrompt(true)
        }, RETRY_PROMPT_DELAY_MS)
        return () => clearTimeout(retryTimer)
    }, [])

    return (
        <div className="h-screen bg-primary flex flex-col items-center justify-center gap-3 text-center p-4">
            {showSpinner && <Spinner className="text-5xl" />}
            {showRetryPrompt && (
                <>
                    <p className="max-w-100 text-secondary">
                        PostHog is taking longer than usual to load. This can happen right after a new version ships.
                    </p>
                    <LemonButton
                        type="primary"
                        data-attr="authenticated-shell-fallback-reload"
                        onClick={() => window.location.reload()}
                    >
                        Reload
                    </LemonButton>
                </>
            )}
        </div>
    )
}
