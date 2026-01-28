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
const ExperimentsJSWebInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: JSWebInstallation,
    snippets: JS_WEB_SNIPPETS,
})
const ExperimentsReactInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ReactInstallation,
    snippets: REACT_SNIPPETS,
    wizardIntegrationName: 'React',
})
const ExperimentsNodeInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NodeJSInstallation,
    snippets: NODE_SNIPPETS,
})
const ExperimentsPythonInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: PythonInstallation,
    snippets: PYTHON_SNIPPETS,
})
const ExperimentsPHPInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: PHPInstallation,
    snippets: SERVER_SDK_SNIPPETS,
})
const ExperimentsRubyInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: RubyInstallation,
    snippets: SERVER_SDK_SNIPPETS,
})
const ExperimentsGoInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: GoInstallation,
    snippets: SERVER_SDK_SNIPPETS,
})

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
const ExperimentsNextJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NextJSInstallation,
    snippets: SSR_FRAMEWORK_SNIPPETS,
    wizardIntegrationName: 'Next.js',
})
const ExperimentsSvelteInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SvelteInstallation,
    snippets: SSR_FRAMEWORK_SNIPPETS,
    wizardIntegrationName: 'Svelte',
})
const ExperimentsRemixJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: RemixInstallation,
    snippets: SSR_FRAMEWORK_SNIPPETS,
})
const ExperimentsNuxtJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NuxtInstallation,
    snippets: SSR_FRAMEWORK_SNIPPETS,
})

// JS Frameworks (with wizard support where available)
const ExperimentsAngularInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AngularInstallation,
    snippets: JS_FRAMEWORK_SNIPPETS,
})
const ExperimentsAstroInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AstroInstallation,
    snippets: JS_FRAMEWORK_SNIPPETS,
    wizardIntegrationName: 'Astro',
})
const ExperimentsBubbleInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: BubbleInstallation,
    snippets: JS_FRAMEWORK_SNIPPETS,
})
const ExperimentsFramerInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: FramerInstallation,
    snippets: JS_FRAMEWORK_SNIPPETS,
})
const ExperimentsVueInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: VueInstallation,
    snippets: JS_FRAMEWORK_SNIPPETS,
})
const ExperimentsWebflowInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: WebflowInstallation,
    snippets: JS_FRAMEWORK_SNIPPETS,
})

// Python frameworks (with wizard support)
const ExperimentsDjangoInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: DjangoInstallation,
    snippets: PYTHON_SNIPPETS,
    wizardIntegrationName: 'Django',
})

// PHP frameworks
const ExperimentsLaravelInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: LaravelInstallation,
    snippets: SERVER_SDK_SNIPPETS,
})

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
    [SDKKey.TANSTACK_START]: withOnboardingDocsWrapper({
        Installation: ReactInstallation,
        snippets: REACT_SNIPPETS,
        wizardIntegrationName: 'React',
    }),
    [SDKKey.REMIX]: ExperimentsRemixJSInstructionsWrapper,
    [SDKKey.RUBY]: ExperimentsRubyInstructionsWrapper,
    [SDKKey.SVELTE]: ExperimentsSvelteInstructionsWrapper,
    [SDKKey.VITE]: withOnboardingDocsWrapper({
        Installation: ReactInstallation,
        snippets: REACT_SNIPPETS,
        wizardIntegrationName: 'React',
    }),
    [SDKKey.VUE_JS]: ExperimentsVueInstructionsWrapper,
    [SDKKey.WEBFLOW]: ExperimentsWebflowInstructionsWrapper,
}
