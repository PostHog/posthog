import { APIInstallation } from '@posthog/shared-onboarding/product-analytics/api'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsAPIInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <APIInstallation />
        </OnboardingDocsContentWrapper>
    )
}
