import { JSEventCapture } from '@posthog/shared-onboarding/product-analytics'
import {
    FlutterInstallation,
    HTMLSnippetInstallation,
    JSWebInstallation,
    NextJSInstallation,
    ReactInstallation,
    ReactNativeInstallation,
    iOSInstallation,
} from '@posthog/shared-onboarding/surveys'

import { SDKInstructionsMap, SDKKey } from '~/types'

import { withOnboardingDocsWrapper } from '../shared/onboardingWrappers'

const JS_WEB_SNIPPETS = {
    JSEventCapture,
}

const SurveysJSWebInstructionsWrapper = withOnboardingDocsWrapper(JSWebInstallation, JS_WEB_SNIPPETS)
const SurveysNextJSInstructionsWrapper = withOnboardingDocsWrapper(NextJSInstallation, JS_WEB_SNIPPETS)
const SurveysHTMLSnippetInstructionsWrapper = withOnboardingDocsWrapper(HTMLSnippetInstallation, JS_WEB_SNIPPETS)
const SurveysReactInstructionsWrapper = withOnboardingDocsWrapper(ReactInstallation, JS_WEB_SNIPPETS)
const SurveysReactNativeInstructionsWrapper = withOnboardingDocsWrapper(ReactNativeInstallation)
const SurveysiOSInstructionsWrapper = withOnboardingDocsWrapper(iOSInstallation)
const SurveysFlutterInstructionsWrapper = withOnboardingDocsWrapper(FlutterInstallation)

export const SurveysSDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: SurveysJSWebInstructionsWrapper,
    [SDKKey.NEXT_JS]: SurveysNextJSInstructionsWrapper,
    [SDKKey.HTML_SNIPPET]: SurveysHTMLSnippetInstructionsWrapper,
    [SDKKey.REACT]: SurveysReactInstructionsWrapper,
    [SDKKey.REACT_NATIVE]: SurveysReactNativeInstructionsWrapper,
    [SDKKey.IOS]: SurveysiOSInstructionsWrapper,
    [SDKKey.FLUTTER]: SurveysFlutterInstructionsWrapper,
    /*
    [SDKKey.ANGULAR]: AngularInstructions,
    [SDKKey.ASTRO]: AstroInstructions,
    [SDKKey.BUBBLE]: BubbleInstructions,
    [SDKKey.FRAMER]: FramerInstructions,
    [SDKKey.NUXT_JS]: NuxtJSInstructions,
    [SDKKey.REACT]: ReactInstructions,
    [SDKKey.REMIX]: RemixInstructions,
    [SDKKey.TANSTACK_START]: ReactInstructions,
    [SDKKey.SVELTE]: SvelteInstructions,
    [SDKKey.VITE]: ReactInstructions,
    [SDKKey.VUE_JS]: VueInstructions,
    [SDKKey.WEBFLOW]: WebflowInstructions,
    [SDKKey.IOS]: iOSInstructions,
    [SDKKey.FLUTTER]: FlutterInstructions,
    [SDKKey.REACT_NATIVE]: RNInstructions,
*/
}
