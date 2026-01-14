import { JSEventCapture } from '@posthog/shared-onboarding/product-analytics/_snippets/js-event-capture'
import { WebflowInstallation } from '@posthog/shared-onboarding/product-analytics/webflow'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsWebflowInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper snippets={{ JSEventCapture }}>
            <WebflowInstallation />
        </OnboardingDocsContentWrapper>
    )
}
