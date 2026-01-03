import { BooleanFlagSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/boolean-flag'
import { MultivariateFlagSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/multivariate-flag'
import { OverridePropertiesSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/override-properties'
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
