import {
    APIInstallation,
    BooleanFlagSnippet,
    FlagPayloadSnippet,
    GoInstallation,
    JSWebInstallation,
    MultivariateFlagSnippet,
    NodeJSInstallation,
    OnFeatureFlagsCallbackSnippet,
    OverridePropertiesSnippet,
    PHPInstallation,
    PythonInstallation,
    ReactInstallation,
    ReloadFlagsSnippet,
    RubyInstallation,
} from '@posthog/shared-onboarding/feature-flags'
import {
    AndroidInstallation,
    AngularInstallation,
    AstroInstallation,
    BubbleInstallation,
    DjangoInstallation,
    FlutterInstallation,
    FramerInstallation,
    IOSInstallation,
    LaravelInstallation,
    NextJSInstallation,
    NuxtInstallation,
    ReactNativeInstallation,
    RemixInstallation,
    SvelteInstallation,
    VueInstallation,
    WebflowInstallation,
} from '@posthog/shared-onboarding/product-analytics'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { SDKInstructionsMap, SDKKey } from '~/types'

import { AdvertiseMobileReplay } from '../session-replay/SessionReplaySDKInstructions'
import { FlagImplementationSnippet } from './flagImplementationSnippet'

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

// Helper to create components with Installation + FlagImplementationSnippet
function withFlagImplementation(
    Installation: React.ComponentType,
    sdkKey: SDKKey,
    snippets?: Record<string, React.ComponentType<any>>
): () => JSX.Element {
    return function WrappedInstallation() {
        return (
            <OnboardingDocsContentWrapper snippets={snippets}>
                <Installation />
                <FlagImplementationSnippet sdkKey={sdkKey} />
            </OnboardingDocsContentWrapper>
        )
    }
}

// Helper to create components with Installation + FlagImplementationSnippet + AdvertiseMobileReplay
function withFlagImplementationAndReplay(
    Installation: React.ComponentType,
    sdkKey: SDKKey,
    snippets?: Record<string, React.ComponentType<any>>
): () => JSX.Element {
    return function WrappedInstallation() {
        return (
            <OnboardingDocsContentWrapper snippets={snippets}>
                <Installation />
                <FlagImplementationSnippet sdkKey={sdkKey} />
                <AdvertiseMobileReplay context="flags-onboarding" sdkKey={sdkKey} />
            </OnboardingDocsContentWrapper>
        )
    }
}

// Helper to create components with Installation + multiple FlagImplementationSnippets (for SSR frameworks)
function withFlagImplementationSSR(
    Installation: React.ComponentType,
    clientSDKKey: SDKKey,
    serverSDKKey: SDKKey,
    snippets?: Record<string, React.ComponentType<any>>
): () => JSX.Element {
    return function WrappedInstallation() {
        return (
            <OnboardingDocsContentWrapper snippets={snippets}>
                <Installation />
                <h3>Client-side rendering</h3>
                <FlagImplementationSnippet sdkKey={clientSDKKey} />
                <h3>Server-side rendering</h3>
                <FlagImplementationSnippet sdkKey={serverSDKKey} />
            </OnboardingDocsContentWrapper>
        )
    }
}

// Wrappers for SDKs that use Installation components from shared-onboarding
const FeatureFlagsJSWebInstructionsWrapper = withOnboardingDocsWrapper(JSWebInstallation, JS_WEB_SNIPPETS)
const FeatureFlagsReactInstructionsWrapper = withOnboardingDocsWrapper(ReactInstallation, REACT_SNIPPETS)
const FeatureFlagsNodeInstructionsWrapper = withOnboardingDocsWrapper(NodeJSInstallation, SERVER_SDK_SNIPPETS)
const FeatureFlagsPythonInstructionsWrapper = withOnboardingDocsWrapper(PythonInstallation, SERVER_SDK_SNIPPETS)
const FeatureFlagsPHPInstructionsWrapper = withOnboardingDocsWrapper(PHPInstallation, SERVER_SDK_SNIPPETS)
const FeatureFlagsRubyInstructionsWrapper = withOnboardingDocsWrapper(RubyInstallation, SERVER_SDK_SNIPPETS)
const FeatureFlagsGoInstructionsWrapper = withOnboardingDocsWrapper(GoInstallation, SERVER_SDK_SNIPPETS)
const FeatureFlagsAPIInstructionsWrapper = withOnboardingDocsWrapper(APIInstallation)

// Wrappers for SDKs using product-analytics Installation components with FlagImplementationSnippet
const FeatureFlagsAngularInstructionsWrapper = withFlagImplementation(AngularInstallation, SDKKey.JS_WEB)
const FeatureFlagsAstroInstructionsWrapper = withFlagImplementation(AstroInstallation, SDKKey.JS_WEB)
const FeatureFlagsBubbleInstructionsWrapper = withFlagImplementation(BubbleInstallation, SDKKey.JS_WEB)
const FeatureFlagsDjangoInstructionsWrapper = withFlagImplementation(DjangoInstallation, SDKKey.PYTHON)
const FeatureFlagsFramerInstructionsWrapper = withFlagImplementation(FramerInstallation, SDKKey.JS_WEB)
const FeatureFlagsLaravelInstructionsWrapper = withFlagImplementation(LaravelInstallation, SDKKey.PHP)
const FeatureFlagsVueInstructionsWrapper = withFlagImplementation(VueInstallation, SDKKey.JS_WEB)
const FeatureFlagsWebflowInstructionsWrapper = withFlagImplementation(WebflowInstallation, SDKKey.JS_WEB)

// Wrappers for mobile SDKs with AdvertiseMobileReplay
const FeatureFlagsAndroidInstructionsWrapper = withFlagImplementationAndReplay(AndroidInstallation, SDKKey.ANDROID)
const FeatureFlagsIOSInstructionsWrapper = withFlagImplementationAndReplay(IOSInstallation, SDKKey.IOS)
const FeatureFlagsFlutterInstructionsWrapper = withFlagImplementationAndReplay(FlutterInstallation, SDKKey.FLUTTER)
const FeatureFlagsRNInstructionsWrapper = withFlagImplementationAndReplay(ReactNativeInstallation, SDKKey.REACT_NATIVE)

// Wrappers for SSR frameworks
const FeatureFlagsNextJSInstructionsWrapper = withFlagImplementationSSR(
    NextJSInstallation,
    SDKKey.REACT,
    SDKKey.NODE_JS
)
const FeatureFlagsSvelteInstructionsWrapper = withFlagImplementationSSR(
    SvelteInstallation,
    SDKKey.JS_WEB,
    SDKKey.NODE_JS
)
const FeatureFlagsRemixJSInstructionsWrapper = withFlagImplementationSSR(
    RemixInstallation,
    SDKKey.JS_WEB,
    SDKKey.NODE_JS
)
const FeatureFlagsNuxtJSInstructionsWrapper = withFlagImplementationSSR(NuxtInstallation, SDKKey.REACT, SDKKey.NODE_JS)

export const FeatureFlagsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: FeatureFlagsJSWebInstructionsWrapper,
    [SDKKey.ANGULAR]: FeatureFlagsAngularInstructionsWrapper,
    [SDKKey.ANDROID]: FeatureFlagsAndroidInstructionsWrapper,
    [SDKKey.API]: FeatureFlagsAPIInstructionsWrapper,
    [SDKKey.ASTRO]: FeatureFlagsAstroInstructionsWrapper,
    [SDKKey.BUBBLE]: FeatureFlagsBubbleInstructionsWrapper,
    [SDKKey.DJANGO]: FeatureFlagsDjangoInstructionsWrapper,
    [SDKKey.FLUTTER]: FeatureFlagsFlutterInstructionsWrapper,
    [SDKKey.FRAMER]: FeatureFlagsFramerInstructionsWrapper,
    [SDKKey.GO]: FeatureFlagsGoInstructionsWrapper,
    [SDKKey.IOS]: FeatureFlagsIOSInstructionsWrapper,
    [SDKKey.LARAVEL]: FeatureFlagsLaravelInstructionsWrapper,
    [SDKKey.NEXT_JS]: FeatureFlagsNextJSInstructionsWrapper,
    [SDKKey.NODE_JS]: FeatureFlagsNodeInstructionsWrapper,
    [SDKKey.NUXT_JS]: FeatureFlagsNuxtJSInstructionsWrapper,
    [SDKKey.PHP]: FeatureFlagsPHPInstructionsWrapper,
    [SDKKey.PYTHON]: FeatureFlagsPythonInstructionsWrapper,
    [SDKKey.REACT]: FeatureFlagsReactInstructionsWrapper,
    [SDKKey.REACT_NATIVE]: FeatureFlagsRNInstructionsWrapper,
    [SDKKey.TANSTACK_START]: FeatureFlagsReactInstructionsWrapper,
    [SDKKey.REMIX]: FeatureFlagsRemixJSInstructionsWrapper,
    [SDKKey.RUBY]: FeatureFlagsRubyInstructionsWrapper,
    [SDKKey.SVELTE]: FeatureFlagsSvelteInstructionsWrapper,
    [SDKKey.VITE]: FeatureFlagsReactInstructionsWrapper,
    [SDKKey.VUE_JS]: FeatureFlagsVueInstructionsWrapper,
    [SDKKey.WEBFLOW]: FeatureFlagsWebflowInstructionsWrapper,
}
