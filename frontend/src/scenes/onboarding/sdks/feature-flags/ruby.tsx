import {
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
    OverridePropertiesSnippet,
} from '@posthog/shared-onboarding/feature-flags'
import { RubyInstallation } from '@posthog/shared-onboarding/feature-flags/ruby'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function FeatureFlagsRubyInstructions(): JSX.Element {
    const snippets = {
        BooleanFlagSnippet,
        MultivariateFlagSnippet,
        OverridePropertiesSnippet,
    }

    return (
        <OnboardingDocsContentWrapper snippets={snippets}>
            <RubyInstallation />
        </OnboardingDocsContentWrapper>
    )
}
