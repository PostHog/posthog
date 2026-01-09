import {
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
    OverridePropertiesSnippet,
} from '@posthog/shared-onboarding/feature-flags'
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
