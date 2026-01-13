import { JSEventCapture } from '@posthog/shared-onboarding/product-analytics/_snippets/js-event-capture'
import { NuxtInstallation } from '@posthog/shared-onboarding/product-analytics/nuxt'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsNuxtJSInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper snippets={{ JSEventCapture }}>
            <NuxtInstallation />
        </OnboardingDocsContentWrapper>
    )
}
