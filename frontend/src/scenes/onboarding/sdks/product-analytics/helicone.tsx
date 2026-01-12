import { HeliconeInstallation } from '@posthog/shared-onboarding/product-analytics/helicone'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsHeliconeInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <HeliconeInstallation />
        </OnboardingDocsContentWrapper>
    )
}
