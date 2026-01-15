import { LangfuseInstallation } from '@posthog/shared-onboarding/product-analytics/langfuse'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsLangfuseInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <LangfuseInstallation />
        </OnboardingDocsContentWrapper>
    )
}
