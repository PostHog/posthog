import { N8nInstallation } from '@posthog/shared-onboarding/product-analytics/n8n'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsN8nInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <N8nInstallation />
        </OnboardingDocsContentWrapper>
    )
}
