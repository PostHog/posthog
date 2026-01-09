import {
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
    OverridePropertiesSnippet,
} from '@posthog/shared-onboarding/feature-flags'
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
