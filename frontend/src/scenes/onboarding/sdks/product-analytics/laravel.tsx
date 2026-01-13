import { LaravelInstallation } from '@posthog/shared-onboarding/product-analytics/laravel'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsLaravelInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <LaravelInstallation />
        </OnboardingDocsContentWrapper>
    )
}
