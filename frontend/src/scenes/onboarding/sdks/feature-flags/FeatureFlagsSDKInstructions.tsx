import {
    FeatureFlagsAndroidInstructions,
    FeatureFlagsAngularInstructions,
    FeatureFlagsAstroInstructions,
    FeatureFlagsBubbleInstructions,
    FeatureFlagsDjangoInstructions,
    FeatureFlagsFlutterInstructions,
    FeatureFlagsFramerInstructions,
    FeatureFlagsIOSInstructions,
    FeatureFlagsLaravelInstructions,
    FeatureFlagsNextJSInstructions,
    FeatureFlagsNuxtJSInstructions,
    FeatureFlagsRNInstructions,
    FeatureFlagsRemixJSInstructions,
    FeatureFlagsSvelteInstructions,
    FeatureFlagsVueInstructions,
    FeatureFlagsWebflowInstructions,
} from '.'

import {
    BooleanFlagSnippet,
    FlagPayloadSnippet,
    MultivariateFlagSnippet,
    OnFeatureFlagsCallbackSnippet,
    OverridePropertiesSnippet,
    ReloadFlagsSnippet,
} from '@posthog/shared-onboarding/feature-flags'
import { APIInstallation } from '@posthog/shared-onboarding/feature-flags/api'
import { GoInstallation } from '@posthog/shared-onboarding/feature-flags/go'
import { JSWebInstallation } from '@posthog/shared-onboarding/feature-flags/js-web'
import { NodeJSInstallation } from '@posthog/shared-onboarding/feature-flags/nodejs'
import { PHPInstallation } from '@posthog/shared-onboarding/feature-flags/php'
import { PythonInstallation } from '@posthog/shared-onboarding/feature-flags/python'
import { ReactInstallation } from '@posthog/shared-onboarding/feature-flags/react'
import { RubyInstallation } from '@posthog/shared-onboarding/feature-flags/ruby'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { SDKInstructionsMap, SDKKey } from '~/types'

// Helper to create wrapped instruction components without recreating snippets on every render
function withOnboardingDocsWrapper(
    Installation: React.ComponentType,
    snippets?: Record<string, React.ComponentType<any>>
): () => JSX.Element {
    return function WrappedInstallation() {
        return (
            <OnboardingDocsContentWrapper snippets={snippets}>
                <Installation />
            </OnboardingDocsContentWrapper>
        )
    }
}

// Snippet configurations (defined once, not recreated on render)
const JS_WEB_SNIPPETS = {
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
    FlagPayloadSnippet,
    OnFeatureFlagsCallbackSnippet,
    ReloadFlagsSnippet,
}

const REACT_SNIPPETS = {
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
    FlagPayloadSnippet,
}

const SERVER_SDK_SNIPPETS = {
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
    OverridePropertiesSnippet,
}

const FeatureFlagsJSWebInstructionsWrapper = withOnboardingDocsWrapper(JSWebInstallation, JS_WEB_SNIPPETS)
const FeatureFlagsReactInstructionsWrapper = withOnboardingDocsWrapper(ReactInstallation, REACT_SNIPPETS)
const FeatureFlagsNodeInstructionsWrapper = withOnboardingDocsWrapper(NodeJSInstallation, SERVER_SDK_SNIPPETS)
const FeatureFlagsPythonInstructionsWrapper = withOnboardingDocsWrapper(PythonInstallation, SERVER_SDK_SNIPPETS)
const FeatureFlagsPHPInstructionsWrapper = withOnboardingDocsWrapper(PHPInstallation, SERVER_SDK_SNIPPETS)
const FeatureFlagsRubyInstructionsWrapper = withOnboardingDocsWrapper(RubyInstallation, SERVER_SDK_SNIPPETS)
const FeatureFlagsGoInstructionsWrapper = withOnboardingDocsWrapper(GoInstallation, SERVER_SDK_SNIPPETS)
const FeatureFlagsAPIInstructionsWrapper = withOnboardingDocsWrapper(APIInstallation)

export const FeatureFlagsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: FeatureFlagsJSWebInstructionsWrapper,
    [SDKKey.ANGULAR]: FeatureFlagsAngularInstructions,
    [SDKKey.ANDROID]: FeatureFlagsAndroidInstructions,
    [SDKKey.API]: FeatureFlagsAPIInstructionsWrapper,
    [SDKKey.ASTRO]: FeatureFlagsAstroInstructions,
    [SDKKey.BUBBLE]: FeatureFlagsBubbleInstructions,
    [SDKKey.DJANGO]: FeatureFlagsDjangoInstructions,
    [SDKKey.FLUTTER]: FeatureFlagsFlutterInstructions,
    [SDKKey.FRAMER]: FeatureFlagsFramerInstructions,
    [SDKKey.GO]: FeatureFlagsGoInstructionsWrapper,
    [SDKKey.IOS]: FeatureFlagsIOSInstructions,
    [SDKKey.LARAVEL]: FeatureFlagsLaravelInstructions,
    [SDKKey.NEXT_JS]: FeatureFlagsNextJSInstructions,
    [SDKKey.NODE_JS]: FeatureFlagsNodeInstructionsWrapper,
    [SDKKey.NUXT_JS]: FeatureFlagsNuxtJSInstructions,
    [SDKKey.PHP]: FeatureFlagsPHPInstructionsWrapper,
    [SDKKey.PYTHON]: FeatureFlagsPythonInstructionsWrapper,
    [SDKKey.REACT]: FeatureFlagsReactInstructionsWrapper,
    [SDKKey.REACT_NATIVE]: FeatureFlagsRNInstructions,
    [SDKKey.TANSTACK_START]: FeatureFlagsReactInstructionsWrapper,
    [SDKKey.REMIX]: FeatureFlagsRemixJSInstructions,
    [SDKKey.RUBY]: FeatureFlagsRubyInstructionsWrapper,
    [SDKKey.SVELTE]: FeatureFlagsSvelteInstructions,
    [SDKKey.VITE]: FeatureFlagsReactInstructionsWrapper,
    [SDKKey.VUE_JS]: FeatureFlagsVueInstructions,
    [SDKKey.WEBFLOW]: FeatureFlagsWebflowInstructions,
}
