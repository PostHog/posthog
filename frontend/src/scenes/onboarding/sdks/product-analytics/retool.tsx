import { RetoolInstallation } from '@posthog/shared-onboarding/product-analytics/retool'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsRetoolInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <RetoolInstallation />
        </OnboardingDocsContentWrapper>
    )
}
