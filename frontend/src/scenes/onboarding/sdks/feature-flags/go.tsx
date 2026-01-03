import { BooleanFlagSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/boolean-flag'
import { MultivariateFlagSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/multivariate-flag'
import { OverridePropertiesSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/override-properties'
import { GoInstallation } from '@posthog/shared-onboarding/feature-flags/go'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function FeatureFlagsGoInstructions(): JSX.Element {
    const snippets = {
        BooleanFlagSnippet,
        MultivariateFlagSnippet,
        OverridePropertiesSnippet,
    }

    return (
        <OnboardingDocsContentWrapper snippets={snippets}>
            <GoInstallation />
        </OnboardingDocsContentWrapper>
    )
}
