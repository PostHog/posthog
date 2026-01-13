import { JSEventCapture } from '@posthog/shared-onboarding/product-analytics/_snippets/js-event-capture'
import { JSWebInstallation } from '@posthog/shared-onboarding/product-analytics/js-web'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function JSWebInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper snippets={{ JSEventCapture }}>
            <JSWebInstallation />
        </OnboardingDocsContentWrapper>
    )
}
