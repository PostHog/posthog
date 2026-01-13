import { JSEventCapture } from '@posthog/shared-onboarding/product-analytics/_snippets/js-event-capture'
import { VueInstallation } from '@posthog/shared-onboarding/product-analytics/vue'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsVueInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper snippets={{ JSEventCapture }}>
            <VueInstallation />
        </OnboardingDocsContentWrapper>
    )
}
