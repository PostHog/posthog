import {
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
    OverridePropertiesSnippet,
} from '@posthog/shared-onboarding/feature-flags'
import { NodeJSInstallation } from '@posthog/shared-onboarding/feature-flags/nodejs'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function FeatureFlagsNodeInstructions(): JSX.Element {
    const snippets = {
        BooleanFlagSnippet,
        MultivariateFlagSnippet,
        OverridePropertiesSnippet,
    }

    return (
        <OnboardingDocsContentWrapper snippets={snippets}>
            <NodeJSInstallation />
        </OnboardingDocsContentWrapper>
    )
}
