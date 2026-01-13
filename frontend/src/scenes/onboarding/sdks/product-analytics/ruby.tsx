import { RubyInstallation } from '@posthog/shared-onboarding/product-analytics/ruby'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsRubyInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <RubyInstallation />
        </OnboardingDocsContentWrapper>
    )
}
