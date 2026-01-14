import { TraceloopInstallation } from '@posthog/shared-onboarding/product-analytics/traceloop'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsTraceloopInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <TraceloopInstallation />
        </OnboardingDocsContentWrapper>
    )
}
