import { MoEngageInstallation } from '@posthog/shared-onboarding/product-analytics/moengage'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsMoEngageInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <MoEngageInstallation />
        </OnboardingDocsContentWrapper>
    )
}
