import { DocusaurusInstallation } from '@posthog/shared-onboarding/product-analytics/docusaurus'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsDocusaurusInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <DocusaurusInstallation />
        </OnboardingDocsContentWrapper>
    )
}
