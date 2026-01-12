import { SegmentInstallation } from '@posthog/shared-onboarding/product-analytics/segment'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsSegmentInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <SegmentInstallation />
        </OnboardingDocsContentWrapper>
    )
}
