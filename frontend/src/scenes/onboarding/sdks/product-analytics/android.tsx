import { AndroidInstallation } from '@posthog/shared-onboarding/product-analytics/android'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsAndroidInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <AndroidInstallation />
        </OnboardingDocsContentWrapper>
    )
}
