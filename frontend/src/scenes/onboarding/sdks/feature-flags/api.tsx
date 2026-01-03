import { APIInstallation } from '@posthog/shared-onboarding/feature-flags/api'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function FeatureFlagsAPIInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <APIInstallation />
        </OnboardingDocsContentWrapper>
    )
}
