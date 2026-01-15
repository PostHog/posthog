import { PythonEventCapture } from '@posthog/shared-onboarding/product-analytics/_snippets/python-event-capture'
import { DjangoInstallation } from '@posthog/shared-onboarding/product-analytics/django'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsDjangoInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper snippets={{ PythonEventCapture }}>
            <DjangoInstallation />
        </OnboardingDocsContentWrapper>
    )
}
