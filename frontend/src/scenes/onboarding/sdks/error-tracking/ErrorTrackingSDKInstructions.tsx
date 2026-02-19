import {
    APIInstallation,
    AndroidInstallation,
    AngularInstallation,
    FlutterInstallation,
    HonoInstallation,
    JSWebInstallation,
    NextJSInstallation,
    NodeJSInstallation,
    Nuxt36Installation,
    Nuxt37Installation,
    PythonInstallation,
    ReactInstallation,
    ReactNativeInstallation,
    RubyInstallation,
    RubyOnRailsInstallation,
    SvelteInstallation,
} from '@posthog/shared-onboarding/error-tracking'
import { JSEventCapture, PythonEventCapture } from '@posthog/shared-onboarding/product-analytics'

import { SDKInstructionsMap, SDKKey } from '~/types'

import { withOnboardingDocsWrapper } from '../shared/onboardingWrappers'

const JS_WEB_SNIPPETS = {
    JSEventCapture,
}

const PYTHON_SNIPPETS = {
    PythonEventCapture,
}

const ErrorTrackingAngularInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AngularInstallation,
    snippets: JS_WEB_SNIPPETS,
    wizardIntegrationName: 'Angular',
})
const ErrorTrackingJSWebInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: JSWebInstallation,
    snippets: JS_WEB_SNIPPETS,
    wizardIntegrationName: 'JavaScript Web',
})
const ErrorTrackingNextJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NextJSInstallation,
    snippets: JS_WEB_SNIPPETS,
    wizardIntegrationName: 'Next.js',
})
const ErrorTrackingNodeInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NodeJSInstallation,
    wizardIntegrationName: 'Node.js',
})
const ErrorTrackingNuxt37InstructionsWrapper = withOnboardingDocsWrapper({
    Installation: Nuxt37Installation,
    snippets: JS_WEB_SNIPPETS,
    wizardIntegrationName: 'Nuxt 3.7+',
})
const ErrorTrackingNuxt36InstructionsWrapper = withOnboardingDocsWrapper({
    Installation: Nuxt36Installation,
    snippets: JS_WEB_SNIPPETS,
    wizardIntegrationName: 'Nuxt 3.6 and below',
})
const ErrorTrackingPythonInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: PythonInstallation,
    snippets: PYTHON_SNIPPETS,
    wizardIntegrationName: 'Python',
})
const ErrorTrackingReactInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ReactInstallation,
    snippets: JS_WEB_SNIPPETS,
    wizardIntegrationName: 'React',
})
const ErrorTrackingSvelteInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SvelteInstallation,
    snippets: JS_WEB_SNIPPETS,
    wizardIntegrationName: 'Svelte',
})

const ErrorTrackingRubyInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: RubyInstallation,
    wizardIntegrationName: 'Ruby',
})
const ErrorTrackingRubyOnRailsInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: RubyOnRailsInstallation,
})

const ErrorTrackingHonoInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: HonoInstallation,
    wizardIntegrationName: 'Hono',
})
const ErrorTrackingAndroidInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AndroidInstallation,
})
const ErrorTrackingFlutterInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: FlutterInstallation,
})
const ErrorTrackingReactNativeInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ReactNativeInstallation,
})
const ErrorTrackingAPIInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: APIInstallation,
})
export const ErrorTrackingSDKInstructions: SDKInstructionsMap = {
    [SDKKey.ANGULAR]: ErrorTrackingAngularInstructionsWrapper,
    [SDKKey.JS_WEB]: ErrorTrackingJSWebInstructionsWrapper,
    [SDKKey.NEXT_JS]: ErrorTrackingNextJSInstructionsWrapper,
    [SDKKey.NODE_JS]: ErrorTrackingNodeInstructionsWrapper,
    [SDKKey.NUXT_JS]: ErrorTrackingNuxt37InstructionsWrapper,
    [SDKKey.NUXT_JS_36]: ErrorTrackingNuxt36InstructionsWrapper,
    [SDKKey.PYTHON]: ErrorTrackingPythonInstructionsWrapper,
    [SDKKey.REACT]: ErrorTrackingReactInstructionsWrapper,
    [SDKKey.SVELTE]: ErrorTrackingSvelteInstructionsWrapper,
    [SDKKey.TANSTACK_START]: ErrorTrackingReactInstructionsWrapper,
    [SDKKey.VITE]: ErrorTrackingReactInstructionsWrapper,
    [SDKKey.RUBY]: ErrorTrackingRubyInstructionsWrapper,
    [SDKKey.RUBY_ON_RAILS]: ErrorTrackingRubyOnRailsInstructionsWrapper,
    [SDKKey.HONO]: ErrorTrackingHonoInstructionsWrapper,
    [SDKKey.ANDROID]: ErrorTrackingAndroidInstructionsWrapper,
    [SDKKey.FLUTTER]: ErrorTrackingFlutterInstructionsWrapper,
    [SDKKey.REACT_NATIVE]: ErrorTrackingReactNativeInstructionsWrapper,
    [SDKKey.API]: ErrorTrackingAPIInstructionsWrapper,
}
