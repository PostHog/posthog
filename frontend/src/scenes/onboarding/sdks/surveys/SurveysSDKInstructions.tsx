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
    SurveysReactRouterInstallation,
    SurveysRemixInstallation,
    SurveysSvelteInstallation,
    SurveysVueInstallation,
    SurveysWebflowInstallation,
} from '@posthog/shared-onboarding/surveys'

import { SDKInstructionsMap, SDKKey } from '~/types'

import { JS_WEB_SNIPPETS } from '../shared/jsWebSnippets'
import { withOnboardingDocsWrapper } from '../shared/onboardingWrappers'

const SNIPPETS = {
    ...JS_WEB_SNIPPETS,
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
    wizardIntegrationName: 'Angular',
})
const SurveysVueInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SurveysVueInstallation,
    snippets: SNIPPETS,
    wizardIntegrationName: 'Vue',
})
const SurveysNuxtInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SurveysNuxtInstallation,
    snippets: SNIPPETS,
    wizardIntegrationName: 'Nuxt',
})
const SurveysReactRouterInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SurveysReactRouterInstallation,
    snippets: SNIPPETS,
})
const SurveysRemixInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SurveysRemixInstallation,
    snippets: SNIPPETS,
    wizardIntegrationName: 'React Router',
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
    wizardIntegrationName: 'Swift',
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
    [SDKKey.REACT_ROUTER]: SurveysReactRouterInstructionsWrapper,
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
