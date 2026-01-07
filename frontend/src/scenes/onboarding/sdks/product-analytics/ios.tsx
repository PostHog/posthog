import { IOSInstallation } from '@posthog/shared-onboarding/product-analytics/ios'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsIOSInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <IOSInstallation />
        </OnboardingDocsContentWrapper>
    )
}
