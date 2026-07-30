import { Spinner } from '@posthog/lemon-ui'

import { useSelfDrivingRunInFlight } from 'scenes/onboarding/shared/wizard-sync/hooks'

/**
 * A quiet one-liner for empty states while the self-driving wizard is mid-run: the surface is empty
 * because setup hasn't finished, not because nothing works. Renders nothing when no run is going.
 */
export function SelfDrivingInstallingHint(): JSX.Element | null {
    const runInFlight = useSelfDrivingRunInFlight()
    if (!runInFlight) {
        return null
    }
    return (
        <span className="inline-flex items-center gap-1.5 text-xs text-tertiary mt-1">
            <Spinner className="text-sm" />
            Self-driving setup is running. Things start showing up here once it finishes.
        </span>
    )
}
