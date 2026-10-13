import { useEffect, useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'

// After this long the shell is almost certainly stuck (a stale-deploy chunk that
// never resolves), so explain the wait and offer a reload.
const RETRY_PROMPT_DELAY_MS = 8000

/**
 * Suspense fallback for the authenticated shell chunk. It shows a spinner, then
 * explains the wait and offers a reload once the load is clearly stuck. This keeps
 * a hard reload after a stale-deploy chunk swap from leaving the person on a bare
 * full-screen logo with no way forward.
 *
 * `showSpinner` comes from `appLogic.showingDelayedSpinner`, which starts its delay
 * at app boot. The boot spinner can therefore be on screen before this fallback
 * mounts. A second delay timed from mount would hide the spinner again and blank
 * the screen between the two.
 */
export function AuthenticatedShellFallback({ showSpinner }: { showSpinner: boolean }): JSX.Element {
    const [showRetryPrompt, setShowRetryPrompt] = useState(false)

    useEffect(() => {
        const retryTimer = window.setTimeout(() => setShowRetryPrompt(true), RETRY_PROMPT_DELAY_MS)
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
