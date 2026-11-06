import { LemonBanner } from '@posthog/lemon-ui'

export interface FeatureFlagNoConditionsWarningProps {
    conditionSetCount: number
    className?: string
}

// A flag with no release conditions matches nobody, so it always evaluates to false.
// Server-side SDKs that evaluate locally return that false without asking the PostHog
// API, so this warning makes the outcome visible where the conditions are shown.
export function FeatureFlagNoConditionsWarning({
    conditionSetCount,
    className,
}: FeatureFlagNoConditionsWarningProps): JSX.Element | null {
    if (conditionSetCount > 0) {
        return null
    }

    return (
        <LemonBanner type="warning" className={className} data-attr="feature-flag-no-conditions-warning">
            This flag has no release conditions, so it always evaluates to <code>false</code>. Add a condition set to
            release it, for example one set at 100% rollout.
        </LemonBanner>
    )
}
