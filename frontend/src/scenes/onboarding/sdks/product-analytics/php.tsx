import { PHPInstallation } from '@posthog/shared-onboarding/product-analytics/php'
import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsPHPInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <PHPInstallation />
        </OnboardingDocsContentWrapper>
    )
}
