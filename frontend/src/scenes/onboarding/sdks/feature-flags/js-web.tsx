import {
    BooleanFlagSnippet,
    FlagPayloadSnippet,
    MultivariateFlagSnippet,
    OnFeatureFlagsCallbackSnippet,
    ReloadFlagsSnippet,
} from '@posthog/shared-onboarding/feature-flags'
import { JSWebInstallation } from '@posthog/shared-onboarding/feature-flags/js-web'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function FeatureFlagsJSWebInstructions(): JSX.Element {
    const snippets = {
        BooleanFlagSnippet,
        MultivariateFlagSnippet,
        FlagPayloadSnippet,
        OnFeatureFlagsCallbackSnippet,
        ReloadFlagsSnippet,
    }

    return (
        <OnboardingDocsContentWrapper snippets={snippets}>
            <JSWebInstallation />
        </OnboardingDocsContentWrapper>
    )
}
