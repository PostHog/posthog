import { JSEventCapture } from '@posthog/shared-onboarding/product-analytics/_snippets/js-event-capture'
import { RemixInstallation } from '@posthog/shared-onboarding/product-analytics/remix'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsRemixJSInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper snippets={{ JSEventCapture }}>
            <RemixInstallation />
        </OnboardingDocsContentWrapper>
    )
}
