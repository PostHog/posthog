import {
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
    OverridePropertiesSnippet,
} from '@posthog/shared-onboarding/feature-flags'
import { PHPInstallation } from '@posthog/shared-onboarding/feature-flags/php'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function FeatureFlagsPHPInstructions(): JSX.Element {
    const snippets = {
        BooleanFlagSnippet,
        MultivariateFlagSnippet,
        OverridePropertiesSnippet,
    }

    return (
        <OnboardingDocsContentWrapper snippets={snippets}>
            <PHPInstallation />
        </OnboardingDocsContentWrapper>
    )
}
