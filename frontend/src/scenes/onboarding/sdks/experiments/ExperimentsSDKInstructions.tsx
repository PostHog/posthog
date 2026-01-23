import {
    AndroidInstallation,
    AngularInstallation,
    AstroInstallation,
    BubbleInstallation,
    DjangoInstallation,
    ExperimentImplementationSnippet,
    FlutterInstallation,
    FramerInstallation,
    GoInstallation,
    IOSInstallation,
    JSWebInstallation,
    LaravelInstallation,
    NextJSInstallation,
    NodeJSInstallation,
    NuxtInstallation,
    PHPInstallation,
    PythonInstallation,
    ReactInstallation,
    ReactNativeInstallation,
    RemixInstallation,
    RubyInstallation,
    SvelteInstallation,
    VueInstallation,
    WebflowInstallation,
} from '@posthog/shared-onboarding/experiments'
import {
    BooleanFlagSnippet,
    FlagPayloadSnippet,
    MultivariateFlagSnippet,
    OnFeatureFlagsCallbackSnippet,
    OverridePropertiesSnippet,
    ReloadFlagsSnippet,
} from '@posthog/shared-onboarding/feature-flags'
import { JSEventCapture, NodeEventCapture, PythonEventCapture } from '@posthog/shared-onboarding/product-analytics'

import { SDKInstructionsMap, SDKKey } from '~/types'

import { withMobileReplay, withOnboardingDocsWrapper } from '../shared/onboardingWrappers'

// Snippet configurations
// JS Web SDKs - client-side with full JS capabilities
const JS_WEB_SNIPPETS = {
    JSEventCapture,
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
    FlagPayloadSnippet,
    OnFeatureFlagsCallbackSnippet,
    ReloadFlagsSnippet,
    ExperimentImplementationSnippet,
}

// React - client-side with React hooks
const REACT_SNIPPETS = {
    JSEventCapture,
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
    FlagPayloadSnippet,
    ExperimentImplementationSnippet,
}

// Node.js - server-side
const NODE_SNIPPETS = {
    NodeEventCapture,
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
    OverridePropertiesSnippet,
    ExperimentImplementationSnippet,
}

// Python - server-side
const PYTHON_SNIPPETS = {
    PythonEventCapture,
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
    OverridePropertiesSnippet,
    ExperimentImplementationSnippet,
}

// Server SDKs without specific event capture (PHP, Ruby, Go)
const SERVER_SDK_SNIPPETS = {
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
    OverridePropertiesSnippet,
    ExperimentImplementationSnippet,
}

// Mobile/Native SDKs - basic flag support
const MOBILE_SNIPPETS = {
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
    ExperimentImplementationSnippet,
}

// SSR Framework snippets (Next.js, Remix, Nuxt, Svelte)
const SSR_FRAMEWORK_SNIPPETS = {
    JSEventCapture,
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
    ExperimentImplementationSnippet,
}

// JS-based frameworks (Angular, Astro, Bubble, Framer, Vue, Webflow)
const JS_FRAMEWORK_SNIPPETS = {
    JSEventCapture,
    BooleanFlagSnippet,
    MultivariateFlagSnippet,
    ExperimentImplementationSnippet,
}

// Wrapped instruction components
const ExperimentsJSWebInstructionsWrapper = withOnboardingDocsWrapper(JSWebInstallation, JS_WEB_SNIPPETS)
const ExperimentsReactInstructionsWrapper = withOnboardingDocsWrapper(ReactInstallation, REACT_SNIPPETS, 'React')
const ExperimentsNodeInstructionsWrapper = withOnboardingDocsWrapper(NodeJSInstallation, NODE_SNIPPETS)
const ExperimentsPythonInstructionsWrapper = withOnboardingDocsWrapper(PythonInstallation, PYTHON_SNIPPETS)
const ExperimentsPHPInstructionsWrapper = withOnboardingDocsWrapper(PHPInstallation, SERVER_SDK_SNIPPETS)
const ExperimentsRubyInstructionsWrapper = withOnboardingDocsWrapper(RubyInstallation, SERVER_SDK_SNIPPETS)
const ExperimentsGoInstructionsWrapper = withOnboardingDocsWrapper(GoInstallation, SERVER_SDK_SNIPPETS)

// Mobile SDKs with AdvertiseMobileReplay
const ExperimentsAndroidInstructionsWrapper = withMobileReplay({
    Installation: AndroidInstallation,
    sdkKey: SDKKey.ANDROID,
    onboardingContext: 'experiments-onboarding',
    snippets: MOBILE_SNIPPETS,
})
const ExperimentsIOSInstructionsWrapper = withMobileReplay({
    Installation: IOSInstallation,
    sdkKey: SDKKey.IOS,
    onboardingContext: 'experiments-onboarding',
    snippets: MOBILE_SNIPPETS,
})
const ExperimentsFlutterInstructionsWrapper = withMobileReplay({
    Installation: FlutterInstallation,
    sdkKey: SDKKey.FLUTTER,
    onboardingContext: 'experiments-onboarding',
    snippets: MOBILE_SNIPPETS,
})
const ExperimentsRNInstructionsWrapper = withMobileReplay({
    Installation: ReactNativeInstallation,
    sdkKey: SDKKey.REACT_NATIVE,
    onboardingContext: 'experiments-onboarding',
    snippets: MOBILE_SNIPPETS,
    wizardIntegrationName: 'React Native',
})

// SSR Frameworks (with wizard support where available)
const ExperimentsNextJSInstructionsWrapper = withOnboardingDocsWrapper(
    NextJSInstallation,
    SSR_FRAMEWORK_SNIPPETS,
    'Next.js'
)
const ExperimentsSvelteInstructionsWrapper = withOnboardingDocsWrapper(
    SvelteInstallation,
    SSR_FRAMEWORK_SNIPPETS,
    'Svelte'
)
const ExperimentsRemixJSInstructionsWrapper = withOnboardingDocsWrapper(RemixInstallation, SSR_FRAMEWORK_SNIPPETS)
const ExperimentsNuxtJSInstructionsWrapper = withOnboardingDocsWrapper(NuxtInstallation, SSR_FRAMEWORK_SNIPPETS)

// JS Frameworks (with wizard support where available)
const ExperimentsAngularInstructionsWrapper = withOnboardingDocsWrapper(AngularInstallation, JS_FRAMEWORK_SNIPPETS)
const ExperimentsAstroInstructionsWrapper = withOnboardingDocsWrapper(AstroInstallation, JS_FRAMEWORK_SNIPPETS, 'Astro')
const ExperimentsBubbleInstructionsWrapper = withOnboardingDocsWrapper(BubbleInstallation, JS_FRAMEWORK_SNIPPETS)
const ExperimentsFramerInstructionsWrapper = withOnboardingDocsWrapper(FramerInstallation, JS_FRAMEWORK_SNIPPETS)
const ExperimentsVueInstructionsWrapper = withOnboardingDocsWrapper(VueInstallation, JS_FRAMEWORK_SNIPPETS)
const ExperimentsWebflowInstructionsWrapper = withOnboardingDocsWrapper(WebflowInstallation, JS_FRAMEWORK_SNIPPETS)

// Python frameworks (with wizard support)
const ExperimentsDjangoInstructionsWrapper = withOnboardingDocsWrapper(DjangoInstallation, PYTHON_SNIPPETS, 'Django')

// PHP frameworks
const ExperimentsLaravelInstructionsWrapper = withOnboardingDocsWrapper(LaravelInstallation, SERVER_SDK_SNIPPETS)

export const ExperimentsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: ExperimentsJSWebInstructionsWrapper,
    [SDKKey.ANDROID]: ExperimentsAndroidInstructionsWrapper,
    [SDKKey.ANGULAR]: ExperimentsAngularInstructionsWrapper,
    [SDKKey.ASTRO]: ExperimentsAstroInstructionsWrapper,
    [SDKKey.BUBBLE]: ExperimentsBubbleInstructionsWrapper,
    [SDKKey.DJANGO]: ExperimentsDjangoInstructionsWrapper,
    [SDKKey.FLUTTER]: ExperimentsFlutterInstructionsWrapper,
    [SDKKey.FRAMER]: ExperimentsFramerInstructionsWrapper,
    [SDKKey.GO]: ExperimentsGoInstructionsWrapper,
    [SDKKey.IOS]: ExperimentsIOSInstructionsWrapper,
    [SDKKey.LARAVEL]: ExperimentsLaravelInstructionsWrapper,
    [SDKKey.NEXT_JS]: ExperimentsNextJSInstructionsWrapper,
    [SDKKey.NODE_JS]: ExperimentsNodeInstructionsWrapper,
    [SDKKey.NUXT_JS]: ExperimentsNuxtJSInstructionsWrapper,
    [SDKKey.PHP]: ExperimentsPHPInstructionsWrapper,
    [SDKKey.PYTHON]: ExperimentsPythonInstructionsWrapper,
    [SDKKey.REACT]: ExperimentsReactInstructionsWrapper,
    [SDKKey.REACT_NATIVE]: ExperimentsRNInstructionsWrapper,
    [SDKKey.TANSTACK_START]: withOnboardingDocsWrapper(ReactInstallation, REACT_SNIPPETS, 'React'),
    [SDKKey.REMIX]: ExperimentsRemixJSInstructionsWrapper,
    [SDKKey.RUBY]: ExperimentsRubyInstructionsWrapper,
    [SDKKey.SVELTE]: ExperimentsSvelteInstructionsWrapper,
    [SDKKey.VITE]: withOnboardingDocsWrapper(ReactInstallation, REACT_SNIPPETS, 'React'),
    [SDKKey.VUE_JS]: ExperimentsVueInstructionsWrapper,
    [SDKKey.WEBFLOW]: ExperimentsWebflowInstructionsWrapper,
}
