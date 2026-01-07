import { FlutterInstallation } from '@posthog/shared-onboarding/product-analytics/flutter'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsFlutterInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <FlutterInstallation />
        </OnboardingDocsContentWrapper>
    )
}
