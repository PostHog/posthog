import { RudderstackInstallation } from '@posthog/shared-onboarding/product-analytics/rudderstack'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsRudderstackInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <RudderstackInstallation />
        </OnboardingDocsContentWrapper>
    )
}
