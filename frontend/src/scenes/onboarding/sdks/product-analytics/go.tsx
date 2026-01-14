import { GoInstallation } from '@posthog/shared-onboarding/product-analytics/go'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsGoInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <GoInstallation />
        </OnboardingDocsContentWrapper>
    )
}
