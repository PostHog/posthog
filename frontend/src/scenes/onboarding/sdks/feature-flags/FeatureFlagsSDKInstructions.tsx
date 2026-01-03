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

import { BooleanFlagSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/boolean-flag'
import { FlagPayloadSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/flag-payload'
import { MultivariateFlagSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/multivariate-flag'
import { OnFeatureFlagsCallbackSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/on-feature-flags-callback'
import { OverridePropertiesSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/override-properties'
import { ReloadFlagsSnippet } from '@posthog/shared-onboarding/feature-flags/_snippets/reload-flags'
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

function FeatureFlagsJSWebInstructionsWrapper(): JSX.Element {
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

function FeatureFlagsReactInstructionsWrapper(): JSX.Element {
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

function FeatureFlagsNodeInstructionsWrapper(): JSX.Element {
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

function FeatureFlagsPythonInstructionsWrapper(): JSX.Element {
    const snippets = {
        BooleanFlagSnippet,
        MultivariateFlagSnippet,
        OverridePropertiesSnippet,
    }

    return (
        <OnboardingDocsContentWrapper snippets={snippets}>
            <PythonInstallation />
        </OnboardingDocsContentWrapper>
    )
}

function FeatureFlagsPHPInstructionsWrapper(): JSX.Element {
    const snippets = {
        BooleanFlagSnippet,
        MultivariateFlagSnippet,
        OverridePropertiesSnippet,
    }

    return (
        <OnboardingDocsContentWrapper snippets={snippets}>
            <PHPInstallation />
        </OnboardingDocsContentWrapper>
    )
}

function FeatureFlagsRubyInstructionsWrapper(): JSX.Element {
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

function FeatureFlagsGoInstructionsWrapper(): JSX.Element {
    const snippets = {
        BooleanFlagSnippet,
        MultivariateFlagSnippet,
        OverridePropertiesSnippet,
    }

    return (
        <OnboardingDocsContentWrapper snippets={snippets}>
            <GoInstallation />
        </OnboardingDocsContentWrapper>
    )
}

function FeatureFlagsAPIInstructionsWrapper(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <APIInstallation />
        </OnboardingDocsContentWrapper>
    )
}

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
