import { NodeEventCapture } from '@posthog/shared-onboarding/product-analytics/_snippets/node-event-capture'
import { NodeJSInstallation } from '@posthog/shared-onboarding/product-analytics/nodejs'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsNodeInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper snippets={{ NodeEventCapture }}>
            <NodeJSInstallation />
        </OnboardingDocsContentWrapper>
    )
}
