import { JSEventCapture } from '@posthog/shared-onboarding/product-analytics'
import {
    SurveysAngularInstallation,
    SurveysAstroInstallation,
    SurveysBubbleInstallation,
    SurveysFinalSteps,
    SurveysFlutterInstallation,
    SurveysFramerInstallation,
    SurveysIOSInstallation,
    SurveysWebInstallation,
    SurveysNextJSInstallation,
    SurveysNuxtInstallation,
    SurveysReactInstallation,
    SurveysReactNativeInstallation,
    SurveysRemixInstallation,
    SurveysSvelteInstallation,
    SurveysVueInstallation,
    SurveysWebflowInstallation,
} from '@posthog/shared-onboarding/surveys'

import { SDKInstructionsMap, SDKKey } from '~/types'

import { withOnboardingDocsWrapper } from '../shared/onboardingWrappers'

const SNIPPETS = {
    JSEventCapture,
    SurveysFinalSteps,
}

// JS Web SDKs
const SurveysWebInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SurveysWebInstallation,
    snippets: SNIPPETS,
})

// Frontend frameworks
const SurveysReactInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SurveysReactInstallation,
    snippets: SNIPPETS,
    wizardIntegrationName: 'React',
})
const SurveysNextJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SurveysNextJSInstallation,
    snippets: SNIPPETS,
    wizardIntegrationName: 'Next.js',
})
const SurveysSvelteInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SurveysSvelteInstallation,
    snippets: SNIPPETS,
    wizardIntegrationName: 'Svelte',
})
const SurveysAstroInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SurveysAstroInstallation,
    snippets: SNIPPETS,
    wizardIntegrationName: 'Astro',
})
const SurveysAngularInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SurveysAngularInstallation,
    snippets: SNIPPETS,
})
const SurveysVueInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SurveysVueInstallation,
    snippets: SNIPPETS,
})
const SurveysNuxtInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SurveysNuxtInstallation,
    snippets: SNIPPETS,
})
const SurveysRemixInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SurveysRemixInstallation,
    snippets: SNIPPETS,
})

// Website builders
const SurveysBubbleInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SurveysBubbleInstallation,
    snippets: SNIPPETS,
})
const SurveysFramerInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SurveysFramerInstallation,
    snippets: SNIPPETS,
})
const SurveysWebflowInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SurveysWebflowInstallation,
    snippets: SNIPPETS,
})

// Mobile SDKs
const SurveysIOSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SurveysIOSInstallation,
    snippets: SNIPPETS,
})
const SurveysFlutterInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SurveysFlutterInstallation,
    snippets: SNIPPETS,
})
const SurveysRNInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SurveysReactNativeInstallation,
    snippets: SNIPPETS,
    wizardIntegrationName: 'React Native',
})

export const SurveysSDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: SurveysWebInstructionsWrapper,
    [SDKKey.ANGULAR]: SurveysAngularInstructionsWrapper,
    [SDKKey.ASTRO]: SurveysAstroInstructionsWrapper,
    [SDKKey.BUBBLE]: SurveysBubbleInstructionsWrapper,
    [SDKKey.FRAMER]: SurveysFramerInstructionsWrapper,
    [SDKKey.NEXT_JS]: SurveysNextJSInstructionsWrapper,
    [SDKKey.NUXT_JS]: SurveysNuxtInstructionsWrapper,
    [SDKKey.REACT]: SurveysReactInstructionsWrapper,
    [SDKKey.REMIX]: SurveysRemixInstructionsWrapper,
    [SDKKey.TANSTACK_START]: SurveysReactInstructionsWrapper,
    [SDKKey.SVELTE]: SurveysSvelteInstructionsWrapper,
    [SDKKey.VITE]: SurveysReactInstructionsWrapper,
    [SDKKey.VUE_JS]: SurveysVueInstructionsWrapper,
    [SDKKey.WEBFLOW]: SurveysWebflowInstructionsWrapper,
    [SDKKey.IOS]: SurveysIOSInstructionsWrapper,
    [SDKKey.FLUTTER]: SurveysFlutterInstructionsWrapper,
    [SDKKey.REACT_NATIVE]: SurveysRNInstructionsWrapper,
}
