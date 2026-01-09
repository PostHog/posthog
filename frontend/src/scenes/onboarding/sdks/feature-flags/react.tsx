import {
    BooleanFlagSnippet,
    FlagPayloadSnippet,
    MultivariateFlagSnippet,
} from '@posthog/shared-onboarding/feature-flags'
import { ReactInstallation } from '@posthog/shared-onboarding/feature-flags/react'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function FeatureFlagsReactInstructions(): JSX.Element {
    const snippets = {
        BooleanFlagSnippet,
        MultivariateFlagSnippet,
        FlagPayloadSnippet,
    }

    return (
        <OnboardingDocsContentWrapper snippets={snippets}>
            <ReactInstallation />
        </OnboardingDocsContentWrapper>
    )
}
