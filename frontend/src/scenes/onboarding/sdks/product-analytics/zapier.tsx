import { ZapierInstallation } from '@posthog/shared-onboarding/product-analytics/zapier'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsZapierInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <ZapierInstallation />
        </OnboardingDocsContentWrapper>
    )
}
