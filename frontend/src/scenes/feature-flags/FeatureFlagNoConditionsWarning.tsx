import { LemonBanner } from '@posthog/lemon-ui'
import { Callout, CalloutIcon, ItemContent, ItemDescription } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

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
    const quill = useFeatureFlag('LEMON_UI_TO_QUILL')

    if (conditionSetCount > 0) {
        return null
    }

    if (quill) {
        return (
            <Callout tone="warning" className={className} data-attr="feature-flag-no-conditions-warning">
                <CalloutIcon />
                <ItemContent>
                    <ItemDescription>
                        This flag has no release conditions, so it always evaluates to <code>false</code>. Add a
                        condition set to release it, for example one set at 100% rollout.
                    </ItemDescription>
                </ItemContent>
            </Callout>
        )
    }

    return (
        <LemonBanner type="warning" className={className} data-attr="feature-flag-no-conditions-warning">
            This flag has no release conditions, so it always evaluates to <code>false</code>. Add a condition set to
            release it, for example one set at 100% rollout.
        </LemonBanner>
    )
}
