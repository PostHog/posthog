import { JSEventCapture } from '@posthog/shared-onboarding/product-analytics/_snippets/js-event-capture'
import { GoogleTagManagerInstallation } from '@posthog/shared-onboarding/product-analytics/google-tag-manager'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsGoogleTagManagerInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper snippets={{ JSEventCapture }}>
            <GoogleTagManagerInstallation />
        </OnboardingDocsContentWrapper>
    )
}
