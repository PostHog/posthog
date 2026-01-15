import { PythonEventCapture } from '@posthog/shared-onboarding/product-analytics/_snippets/python-event-capture'
import { PythonInstallation } from '@posthog/shared-onboarding/product-analytics/python'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsPythonInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper snippets={{ PythonEventCapture }}>
            <PythonInstallation />
        </OnboardingDocsContentWrapper>
    )
}
