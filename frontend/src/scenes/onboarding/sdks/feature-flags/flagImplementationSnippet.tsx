import { BooleanFlagSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/boolean-flag'
import { MultivariateFlagSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/multivariate-flag'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { SDKKey } from '~/types'

const sdkKeyToLanguageMap: Record<SDKKey, string> = {
    [SDKKey.JS_WEB]: 'javascript',
    [SDKKey.REACT]: 'react',
    [SDKKey.NODE_JS]: 'node.js',
    [SDKKey.PYTHON]: 'python',
    [SDKKey.PHP]: 'php',
    [SDKKey.RUBY]: 'ruby',
    [SDKKey.GO]: 'go',
    [SDKKey.ANDROID]: 'android',
    [SDKKey.IOS]: 'ios',
    [SDKKey.REACT_NATIVE]: 'react-native',
    [SDKKey.FLUTTER]: 'flutter',
    [SDKKey.ANGULAR]: 'javascript',
    [SDKKey.ASTRO]: 'javascript',
    [SDKKey.BUBBLE]: 'javascript',
    [SDKKey.DJANGO]: 'python',
    [SDKKey.FRAMER]: 'javascript',
    [SDKKey.LARAVEL]: 'php',
    [SDKKey.NEXT_JS]: 'javascript',
    [SDKKey.NUXT_JS]: 'javascript',
    [SDKKey.REMIX]: 'javascript',
    [SDKKey.SVELTE]: 'javascript',
    [SDKKey.VUE_JS]: 'javascript',
    [SDKKey.WEBFLOW]: 'javascript',
    [SDKKey.API]: 'javascript',
    [SDKKey.TANSTACK_START]: 'react',
    [SDKKey.VITE]: 'react',
}

function FlagImplementationSnippetContent({ sdkKey }: { sdkKey: SDKKey }): JSX.Element {
    const language = sdkKeyToLanguageMap[sdkKey] || 'javascript'

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
