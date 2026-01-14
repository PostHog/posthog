import { JSEventCapture } from '@posthog/shared-onboarding/product-analytics/_snippets/js-event-capture'
import { AngularInstallation } from '@posthog/shared-onboarding/product-analytics/angular'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsAngularInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper snippets={{ JSEventCapture }}>
            <AngularInstallation />
        </OnboardingDocsContentWrapper>
    )
}
