import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { wizardProgressTrackerLogic } from '../wizardProgressTrackerLogic'
import { bannerTypeFor, headlineFor, subLineFor } from './helpers'

/**
 * Inline confirmation card shown on the install step once a wizard session
 * exists. The FAB carries the live progress everywhere else — this card just
 * acknowledges the run so the user knows they can keep moving in onboarding.
 */
export function WizardProgressTracker(): JSX.Element | null {
    const { displayState, latestSession } = useValues(wizardProgressTrackerLogic)
    const { setPanelMounted } = useActions(wizardProgressTrackerLogic)

    useEffect(() => {
        setPanelMounted(true)
        return () => setPanelMounted(false)
    }, [setPanelMounted])

    if (displayState === 'preTakeover' || !latestSession) {
        return null
    }

    const errorPayload =
        displayState === 'error' && latestSession.error && typeof latestSession.error === 'object'
            ? (latestSession.error as { type?: string; message?: string })
            : null

    return (
        <LemonBanner type={bannerTypeFor(displayState)}>
            <div className="min-w-0 space-y-1">
                <div className="font-semibold">{headlineFor(displayState)}</div>
                {displayState === 'error' && errorPayload ? (
                    <div className="text-xs">
                        <span className="font-semibold">{errorPayload.type}: </span>
                        <span className="text-muted">{errorPayload.message}</span>
                    </div>
                ) : (
                    <div className="text-xs text-muted flex items-center flex-wrap gap-x-2 gap-y-1">
                        <span>{subLineFor(displayState)}</span>
                    </div>
                )}
            </div>
        </LemonBanner>
    )
}

/**
 * Used by the parent variant to decide whether to render the takeover at all.
 * Mounts the logic on first call. Returns `true` once we have observed a
 * recent session — stale terminal sessions sitting in the DB don't trigger it.
 */
export function useWizardTakeoverActive(): boolean {
    const { displayState, sessionIsCurrent } = useValues(wizardProgressTrackerLogic)
    return displayState !== 'preTakeover' && sessionIsCurrent
}
