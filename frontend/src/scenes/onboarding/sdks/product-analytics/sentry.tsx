import { SentryInstallation } from '@posthog/shared-onboarding/product-analytics/sentry'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsSentryInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <SentryInstallation />
        </OnboardingDocsContentWrapper>
    )
}
