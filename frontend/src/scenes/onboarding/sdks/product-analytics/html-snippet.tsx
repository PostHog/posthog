import { JSEventCapture } from '@posthog/shared-onboarding/product-analytics/_snippets/js-event-capture'
import { HTMLSnippetInstallation } from '@posthog/shared-onboarding/product-analytics/html-snippet'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function HTMLSnippetInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper snippets={{ JSEventCapture }}>
            <HTMLSnippetInstallation />
        </OnboardingDocsContentWrapper>
    )
}
