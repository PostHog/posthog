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

import { SDKInstructionsMap, SDKKey } from '~/types'

import { withMobileReplay, withOnboardingDocsWrapper } from '../shared/onboardingWrappers'

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

// Wrappers for SDKs that use Installation components from shared-onboarding
const FeatureFlagsJSWebInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: JSWebInstallation,
    snippets: JS_WEB_SNIPPETS,
})
const FeatureFlagsReactInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ReactInstallation,
    snippets: REACT_SNIPPETS,
})
const FeatureFlagsNodeInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NodeJSInstallation,
    snippets: NODE_SNIPPETS,
})
const FeatureFlagsPythonInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: PythonInstallation,
    snippets: PYTHON_SNIPPETS,
})
const FeatureFlagsPHPInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: PHPInstallation,
    snippets: SERVER_SDK_SNIPPETS,
})
const FeatureFlagsRubyInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: RubyInstallation,
    snippets: SERVER_SDK_SNIPPETS,
})
const FeatureFlagsGoInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: GoInstallation,
    snippets: SERVER_SDK_SNIPPETS,
})
const FeatureFlagsAPIInstructionsWrapper = withOnboardingDocsWrapper({ Installation: APIInstallation })

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

// Wrappers for SDKs using product-analytics Installation components
const FeatureFlagsAngularInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AngularInstallation,
    snippets: ANGULAR_WITH_EVENTS_SNIPPETS,
})
const FeatureFlagsAstroInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AstroInstallation,
    snippets: JS_WEB_WITH_EVENTS_SNIPPETS,
})
const FeatureFlagsBubbleInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: BubbleInstallation,
    snippets: JS_WEB_WITH_EVENTS_SNIPPETS,
})
const FeatureFlagsFramerInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: FramerInstallation,
    snippets: JS_WEB_WITH_EVENTS_SNIPPETS,
})
const FeatureFlagsVueInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: VueInstallation,
    snippets: JS_WEB_WITH_EVENTS_SNIPPETS,
})
const FeatureFlagsWebflowInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: WebflowInstallation,
    snippets: JS_WEB_WITH_EVENTS_SNIPPETS,
})

// Python frameworks
const FeatureFlagsDjangoInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: DjangoInstallation,
    snippets: PYTHON_WITH_EVENTS_SNIPPETS,
})

// PHP frameworks
const FeatureFlagsLaravelInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: LaravelInstallation,
    snippets: FLAG_IMPLEMENTATION_SNIPPETS,
})

// Wrappers for mobile SDKs with AdvertiseMobileReplay
const FeatureFlagsAndroidInstructionsWrapper = withMobileReplay({
    Installation: AndroidInstallation,
    sdkKey: SDKKey.ANDROID,
    onboardingContext: 'flags-onboarding',
    snippets: FLAG_IMPLEMENTATION_SNIPPETS,
})
const FeatureFlagsIOSInstructionsWrapper = withMobileReplay({
    Installation: IOSInstallation,
    sdkKey: SDKKey.IOS,
    onboardingContext: 'flags-onboarding',
    snippets: FLAG_IMPLEMENTATION_SNIPPETS,
})
const FeatureFlagsFlutterInstructionsWrapper = withMobileReplay({
    Installation: FlutterInstallation,
    sdkKey: SDKKey.FLUTTER,
    onboardingContext: 'flags-onboarding',
    snippets: FLAG_IMPLEMENTATION_SNIPPETS,
})
const FeatureFlagsRNInstructionsWrapper = withMobileReplay({
    Installation: ReactNativeInstallation,
    sdkKey: SDKKey.REACT_NATIVE,
    onboardingContext: 'flags-onboarding',
    snippets: FLAG_IMPLEMENTATION_SNIPPETS,
})

// Wrappers for SSR frameworks
const FeatureFlagsNextJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NextJSInstallation,
    snippets: SSR_FRAMEWORK_SNIPPETS,
})
const FeatureFlagsSvelteInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SvelteInstallation,
    snippets: SSR_FRAMEWORK_SNIPPETS,
})
const FeatureFlagsRemixJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: RemixInstallation,
    snippets: SSR_FRAMEWORK_SNIPPETS,
})
const FeatureFlagsNuxtJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NuxtInstallation,
    snippets: SSR_FRAMEWORK_SNIPPETS,
})

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
