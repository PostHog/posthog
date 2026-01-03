import { BooleanFlagSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/boolean-flag'
import { MultivariateFlagSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/multivariate-flag'
import { OverridePropertiesSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/override-properties'
import { PythonInstallation } from '@posthog/shared-onboarding/feature-flags/python'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function FeatureFlagsPythonInstructions(): JSX.Element {
    const snippets = {
        BooleanFlagSnippet,
        MultivariateFlagSnippet,
        OverridePropertiesSnippet,
    }

    return (
        <OnboardingDocsContentWrapper snippets={snippets}>
            <PythonInstallation />
        </OnboardingDocsContentWrapper>
    )
}
