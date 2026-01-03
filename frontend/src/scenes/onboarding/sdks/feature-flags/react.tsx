import { BooleanFlagSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/boolean-flag'
import { FlagPayloadSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/flag-payload'
import { MultivariateFlagSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/multivariate-flag'
import { ReactInstallation } from '@posthog/shared-onboarding/feature-flags/react'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function FeatureFlagsReactInstructions(): JSX.Element {
    const snippets = {
        BooleanFlagSnippet,
        MultivariateFlagSnippet,
        FlagPayloadSnippet,
    }

    return (
        <OnboardingDocsContentWrapper snippets={snippets}>
            <ReactInstallation />
        </OnboardingDocsContentWrapper>
    )
}
