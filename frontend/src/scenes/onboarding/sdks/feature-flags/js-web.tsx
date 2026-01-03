import { BooleanFlagSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/boolean-flag'
import { FlagPayloadSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/flag-payload'
import { MultivariateFlagSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/multivariate-flag'
import { OnFeatureFlagsCallbackSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/on-feature-flags-callback'
import { ReloadFlagsSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/reload-flags'
import { JSWebInstallation } from '@posthog/shared-onboarding/feature-flags/js-web'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function FeatureFlagsJSWebInstructions(): JSX.Element {
    const snippets = {
        BooleanFlagSnippet,
        MultivariateFlagSnippet,
        FlagPayloadSnippet,
        OnFeatureFlagsCallbackSnippet,
        ReloadFlagsSnippet,
    }

    return (
        <OnboardingDocsContentWrapper snippets={snippets}>
            <JSWebInstallation />
        </OnboardingDocsContentWrapper>
    )
}
