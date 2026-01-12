import { ElixirInstallation } from '@posthog/shared-onboarding/product-analytics/elixir'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsElixirInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <ElixirInstallation />
        </OnboardingDocsContentWrapper>
    )
}
