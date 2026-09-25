import posthog from 'posthog-js'
import { useEffect, useRef, useState } from 'react'

import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'

// Count only time the tab is visible. A background tab loads slower, and nobody can see the prompt there.
const RETRY_PROMPT_VISIBLE_DELAY_MS = 8000

/**
 * Suspense fallback for the authenticated shell chunk. It shows a spinner, then
 * explains the wait and offers a reload after a long visible wait. A slow boot and
 * a stuck chunk look the same from here, so the copy does not guess at a cause.
 *
 * `showSpinner` comes from `appLogic.showingDelayedSpinner`, which starts its delay
 * at app boot. The boot spinner can therefore be on screen before this fallback
 * mounts. A second delay timed from mount would hide the spinner again and blank
 * the screen between the two.
 */
export function AuthenticatedShellFallback({ showSpinner }: { showSpinner: boolean }): JSX.Element {
    const [showRetryPrompt, setShowRetryPrompt] = useState(false)
    const { isVisible } = usePageVisibility()
    const remainingMsRef = useRef(RETRY_PROMPT_VISIBLE_DELAY_MS)
    const wasHiddenRef = useRef(!isVisible)

    useEffect(() => {
        if (showRetryPrompt) {
            return
        }
        if (!isVisible) {
            wasHiddenRef.current = true
            return
        }
        const startedAt = performance.now()
        const retryTimer = window.setTimeout(() => {
            setShowRetryPrompt(true)
            posthog.capture('authenticated shell reload prompt shown', {
                boot_elapsed_ms: Math.round(performance.now()),
                page_was_hidden: wasHiddenRef.current,
            })
        }, remainingMsRef.current)
        return () => {
            clearTimeout(retryTimer)
            remainingMsRef.current = Math.max(0, remainingMsRef.current - (performance.now() - startedAt))
        }
    }, [isVisible, showRetryPrompt])

    return (
        <div className="h-screen bg-primary flex flex-col items-center justify-center gap-3 text-center p-4">
            {showSpinner && <Spinner className="text-5xl" />}
            {showRetryPrompt && (
                <>
                    <p className="max-w-100 text-secondary">
                        PostHog is still loading. If nothing changes after a while, reload the page.
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
