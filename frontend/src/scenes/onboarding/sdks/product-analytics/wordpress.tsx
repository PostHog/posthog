import { WordpressInstallation } from '@posthog/shared-onboarding/product-analytics/wordpress'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsWordpressInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <WordpressInstallation />
        </OnboardingDocsContentWrapper>
    )
}
