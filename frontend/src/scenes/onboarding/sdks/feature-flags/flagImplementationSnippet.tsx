import { BooleanFlagSnippet, MultivariateFlagSnippet } from '@posthog/shared-onboarding/feature-flags'

import { SDK_KEY_TO_SNIPPET_LANGUAGE } from 'lib/constants'
import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { SDKKey } from '~/types'

function FlagImplementationSnippetContent({ sdkKey }: { sdkKey: SDKKey }): JSX.Element {
    const language = SDK_KEY_TO_SNIPPET_LANGUAGE[sdkKey] || 'javascript'

    return (
        <>
            <h3>Basic flag implementation</h3>
            <BooleanFlagSnippet language={language} />
            <h3>Multivariate flags</h3>
            <MultivariateFlagSnippet language={language} />
            <h3>Running experiments</h3>
            <p>
                Experiments run on top of our feature flags. Once you've implemented the flag in your code, you run an
                experiment by creating a new experiment in the PostHog dashboard.
            </p>
        </>
    )
}

export const FlagImplementationSnippet = ({ sdkKey }: { sdkKey: SDKKey }): JSX.Element => {
    const snippets = {
        BooleanFlagSnippet,
        MultivariateFlagSnippet,
    }

    return (
        <OnboardingDocsContentWrapper snippets={snippets}>
            <FlagImplementationSnippetContent sdkKey={sdkKey} />
        </OnboardingDocsContentWrapper>
    )
}
