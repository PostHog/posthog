import { JSEventCapture } from '@posthog/shared-onboarding/product-analytics/_snippets/js-event-capture'
import { BubbleInstallation } from '@posthog/shared-onboarding/product-analytics/bubble'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsBubbleInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper snippets={{ JSEventCapture }}>
            <BubbleInstallation />
        </OnboardingDocsContentWrapper>
    )
}
