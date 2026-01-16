import {
    APIInstallation,
    AndroidInstallation,
    AngularInstallation,
    AstroInstallation,
    BooleanFlagSnippet,
    BubbleInstallation,
    DjangoInstallation,
    FlagPayloadSnippet,
    FlutterInstallation,
    FramerInstallation,
    GoInstallation,
    IOSInstallation,
    JSWebInstallation,
    LaravelInstallation,
    MultivariateFlagSnippet,
    NextJSInstallation,
    NodeJSInstallation,
    NuxtInstallation,
    OnFeatureFlagsCallbackSnippet,
    OverridePropertiesSnippet,
    PHPInstallation,
    PythonInstallation,
    ReactInstallation,
    ReactNativeInstallation,
    ReloadFlagsSnippet,
    RemixInstallation,
    RubyInstallation,
    SvelteInstallation,
    VueInstallation,
    WebflowInstallation,
} from '@posthog/shared-onboarding/feature-flags'
import { JSEventCapture, NodeEventCapture, PythonEventCapture } from '@posthog/shared-onboarding/product-analytics'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { SDKInstructionsMap, SDKKey } from '~/types'

import { AdvertiseMobileReplay } from '../session-replay/SessionReplaySDKInstructions'

// Helper to create wrapped instruction components without recreating snippets on every render
function withOnboardingDocsWrapper(
    Installation: React.ComponentType<any>,
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
// These include both event capture (from product-analytics) and flag snippets
const JS_WEB_SNIPPETS = {
    JSEventCapture,
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
    FlagPayloadSnippet,
    OnFeatureFlagsCallbackSnippet,
    ReloadFlagsSnippet,
}

const REACT_SNIPPETS = {
    JSEventCapture,
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
    FlagPayloadSnippet,
}

// Server SDKs that use Node.js - need NodeEventCapture
const NODE_SNIPPETS = {
    NodeEventCapture,
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
    OverridePropertiesSnippet,
}

// Server SDKs that use Python - need PythonEventCapture
const PYTHON_SNIPPETS = {
    PythonEventCapture,
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
    OverridePropertiesSnippet,
}

// Server SDKs that don't use Node.js or Python (PHP, Ruby, Go)
const SERVER_SDK_SNIPPETS = {
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
    OverridePropertiesSnippet,
}

// Helper to create components with Installation + FlagImplementationSteps
function withFlagImplementation(
    Installation: React.ComponentType<any>,
    _sdkKey: SDKKey,
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

// Helper to create components with Installation + FlagImplementationSteps + AdvertiseMobileReplay
function withFlagImplementationAndReplay(
    Installation: React.ComponentType<any>,
    sdkKey: SDKKey,
    snippets?: Record<string, React.ComponentType<any>>
): () => JSX.Element {
    return function WrappedInstallation() {
        return (
            <OnboardingDocsContentWrapper snippets={snippets}>
                <Installation />
                <AdvertiseMobileReplay context="flags-onboarding" sdkKey={sdkKey} />
            </OnboardingDocsContentWrapper>
        )
    }
}

// Helper to create components with Installation + FlagImplementationStepsSSR (for SSR frameworks)
// Note: SSR frameworks now use feature-flags Installation components that already include flag steps
function withFlagImplementationSSR(
    Installation: React.ComponentType<any>,
    _clientSDKKey: SDKKey,
    _serverSDKKey: SDKKey,
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

// Wrappers for SDKs that use Installation components from shared-onboarding
const FeatureFlagsJSWebInstructionsWrapper = withOnboardingDocsWrapper(JSWebInstallation, JS_WEB_SNIPPETS)
const FeatureFlagsReactInstructionsWrapper = withOnboardingDocsWrapper(ReactInstallation, REACT_SNIPPETS)
const FeatureFlagsNodeInstructionsWrapper = withOnboardingDocsWrapper(NodeJSInstallation, NODE_SNIPPETS)
const FeatureFlagsPythonInstructionsWrapper = withOnboardingDocsWrapper(PythonInstallation, PYTHON_SNIPPETS)
const FeatureFlagsPHPInstructionsWrapper = withOnboardingDocsWrapper(PHPInstallation, SERVER_SDK_SNIPPETS)
const FeatureFlagsRubyInstructionsWrapper = withOnboardingDocsWrapper(RubyInstallation, SERVER_SDK_SNIPPETS)
const FeatureFlagsGoInstructionsWrapper = withOnboardingDocsWrapper(GoInstallation, SERVER_SDK_SNIPPETS)
const FeatureFlagsAPIInstructionsWrapper = withOnboardingDocsWrapper(APIInstallation)

// Snippet configuration for flag implementation (used by FlagImplementationSteps)
const FLAG_IMPLEMENTATION_SNIPPETS = {
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
}

// Snippet configurations matching ProductAnalyticsSDKInstructions.tsx
// These match exactly what product-analytics uses for the same Installation components
const JS_WEB_SNIPPETS_PA = {
    JSEventCapture,
}

const ANGULAR_SNIPPETS_PA = {
    JSEventCapture,
}

const PYTHON_SNIPPETS_PA = {
    PythonEventCapture,
}

// Combined snippets: product-analytics event capture + feature-flags snippets
const JS_WEB_WITH_EVENTS_SNIPPETS = {
    ...JS_WEB_SNIPPETS_PA,
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
}

const ANGULAR_WITH_EVENTS_SNIPPETS = {
    ...ANGULAR_SNIPPETS_PA,
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
}

const PYTHON_WITH_EVENTS_SNIPPETS = {
    ...PYTHON_SNIPPETS_PA,
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
    OverridePropertiesSnippet,
}

// Snippet configuration for SSR frameworks that use feature-flags Installation components
// These components include product-analytics steps, so they need JSEventCapture
const SSR_FRAMEWORK_SNIPPETS = {
    ...JS_WEB_SNIPPETS_PA,
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
}

// Wrappers for SDKs using product-analytics Installation components with FlagImplementationSteps
// Match the snippets used in ProductAnalyticsSDKInstructions.tsx for the same Installation components
const FeatureFlagsAngularInstructionsWrapper = withFlagImplementation(
    AngularInstallation,
    SDKKey.JS_WEB,
    ANGULAR_WITH_EVENTS_SNIPPETS
)
const FeatureFlagsAstroInstructionsWrapper = withFlagImplementation(
    AstroInstallation,
    SDKKey.JS_WEB,
    JS_WEB_WITH_EVENTS_SNIPPETS
)
const FeatureFlagsBubbleInstructionsWrapper = withFlagImplementation(
    BubbleInstallation,
    SDKKey.JS_WEB,
    JS_WEB_WITH_EVENTS_SNIPPETS
)
const FeatureFlagsFramerInstructionsWrapper = withFlagImplementation(
    FramerInstallation,
    SDKKey.JS_WEB,
    JS_WEB_WITH_EVENTS_SNIPPETS
)
const FeatureFlagsVueInstructionsWrapper = withFlagImplementation(
    VueInstallation,
    SDKKey.JS_WEB,
    JS_WEB_WITH_EVENTS_SNIPPETS
)
const FeatureFlagsWebflowInstructionsWrapper = withFlagImplementation(
    WebflowInstallation,
    SDKKey.JS_WEB,
    JS_WEB_WITH_EVENTS_SNIPPETS
)

// Python frameworks - Django uses PYTHON_SNIPPETS in product-analytics
const FeatureFlagsDjangoInstructionsWrapper = withFlagImplementation(
    DjangoInstallation,
    SDKKey.PYTHON,
    PYTHON_WITH_EVENTS_SNIPPETS
)

// PHP frameworks - Laravel doesn't use event capture snippets in product-analytics
const FeatureFlagsLaravelInstructionsWrapper = withFlagImplementation(
    LaravelInstallation,
    SDKKey.PHP,
    FLAG_IMPLEMENTATION_SNIPPETS
)

// Wrappers for mobile SDKs with AdvertiseMobileReplay
const FeatureFlagsAndroidInstructionsWrapper = withFlagImplementationAndReplay(
    AndroidInstallation,
    SDKKey.ANDROID,
    FLAG_IMPLEMENTATION_SNIPPETS
)
const FeatureFlagsIOSInstructionsWrapper = withFlagImplementationAndReplay(
    IOSInstallation,
    SDKKey.IOS,
    FLAG_IMPLEMENTATION_SNIPPETS
)
const FeatureFlagsFlutterInstructionsWrapper = withFlagImplementationAndReplay(
    FlutterInstallation,
    SDKKey.FLUTTER,
    FLAG_IMPLEMENTATION_SNIPPETS
)
const FeatureFlagsRNInstructionsWrapper = withFlagImplementationAndReplay(
    ReactNativeInstallation,
    SDKKey.REACT_NATIVE,
    FLAG_IMPLEMENTATION_SNIPPETS
)

// Wrappers for SSR frameworks
// These use feature-flags Installation components that include product-analytics steps,
// so they need both flag snippets AND event capture snippets
const FeatureFlagsNextJSInstructionsWrapper = withFlagImplementationSSR(
    NextJSInstallation,
    SDKKey.REACT,
    SDKKey.NODE_JS,
    SSR_FRAMEWORK_SNIPPETS
)
const FeatureFlagsSvelteInstructionsWrapper = withFlagImplementationSSR(
    SvelteInstallation,
    SDKKey.JS_WEB,
    SDKKey.NODE_JS,
    SSR_FRAMEWORK_SNIPPETS
)
const FeatureFlagsRemixJSInstructionsWrapper = withFlagImplementationSSR(
    RemixInstallation,
    SDKKey.JS_WEB,
    SDKKey.NODE_JS,
    SSR_FRAMEWORK_SNIPPETS
)
const FeatureFlagsNuxtJSInstructionsWrapper = withFlagImplementationSSR(
    NuxtInstallation,
    SDKKey.REACT,
    SDKKey.NODE_JS,
    SSR_FRAMEWORK_SNIPPETS
)

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
