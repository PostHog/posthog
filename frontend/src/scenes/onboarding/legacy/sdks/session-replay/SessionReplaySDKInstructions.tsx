import {
    AndroidInstallation,
    AngularInstallation,
    AstroInstallation,
    BubbleInstallation,
    FlutterInstallation,
    FramerInstallation,
    IOSInstallation,
    NextJSInstallation,
    NuxtInstallation,
    ReactInstallation,
    ReactNativeInstallation,
    ReactRouterInstallation,
    RemixInstallation,
    SessionReplayFinalSteps,
    SvelteInstallation,
    VueInstallation,
    WebflowInstallation,
    WebInstallation,
} from '@posthog/shared-onboarding/session-replay'

import { JS_WEB_SNIPPETS } from 'scenes/onboarding/shared/jsWebSnippets'

import { SDKInstructionsMap, SDKKey } from '~/types'

import { withOnboardingDocsWrapper } from '../shared/onboardingWrappers'

// Re-exported for back-compat: callers used to import these from this file.
export { AdvertiseMobileReplay, type AdvertiseMobileReplayContext } from './AdvertiseMobileReplay'

const SNIPPETS = {
    ...JS_WEB_SNIPPETS,
    SessionReplayFinalSteps,
}

// JS Web SDKs
const SessionReplayWebInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: WebInstallation,
    snippets: SNIPPETS,
})

// Frontend frameworks
const SessionReplayReactInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ReactInstallation,
    snippets: SNIPPETS,
    wizardIntegrationName: 'React',
})
const SessionReplayNextJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NextJSInstallation,
    snippets: SNIPPETS,
    wizardIntegrationName: 'Next.js',
})
const SessionReplaySvelteInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SvelteInstallation,
    snippets: SNIPPETS,
    wizardIntegrationName: 'Svelte',
})
const SessionReplayAstroInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AstroInstallation,
    snippets: SNIPPETS,
    wizardIntegrationName: 'Astro',
})
const SessionReplayAngularInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AngularInstallation,
    snippets: SNIPPETS,
    wizardIntegrationName: 'Angular',
})
const SessionReplayVueInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: VueInstallation,
    snippets: SNIPPETS,
    wizardIntegrationName: 'Vue',
})
const SessionReplayNuxtJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NuxtInstallation,
    snippets: SNIPPETS,
    wizardIntegrationName: 'Nuxt',
})
const SessionReplayReactRouterInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ReactRouterInstallation,
    snippets: SNIPPETS,
    wizardIntegrationName: 'React Router',
})
const SessionReplayRemixJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: RemixInstallation,
    snippets: SNIPPETS,
    wizardIntegrationName: 'React Router',
})

// Website builders
const SessionReplayBubbleInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: BubbleInstallation,
    snippets: SNIPPETS,
})
const SessionReplayFramerInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: FramerInstallation,
    snippets: SNIPPETS,
})
const SessionReplayWebflowInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: WebflowInstallation,
    snippets: SNIPPETS,
})

// Mobile SDKs
const SessionReplayAndroidInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AndroidInstallation,
    snippets: SNIPPETS,
    wizardIntegrationName: 'Android',
})
const SessionReplayIOSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: IOSInstallation,
    snippets: SNIPPETS,
    wizardIntegrationName: 'Swift',
})
const SessionReplayFlutterInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: FlutterInstallation,
    snippets: SNIPPETS,
})
const SessionReplayRNInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ReactNativeInstallation,
    snippets: SNIPPETS,
    wizardIntegrationName: 'React Native',
})

export const SessionReplaySDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: SessionReplayWebInstructionsWrapper,
    [SDKKey.ANGULAR]: SessionReplayAngularInstructionsWrapper,
    [SDKKey.ASTRO]: SessionReplayAstroInstructionsWrapper,
    [SDKKey.BUBBLE]: SessionReplayBubbleInstructionsWrapper,
    [SDKKey.FRAMER]: SessionReplayFramerInstructionsWrapper,
    [SDKKey.NEXT_JS]: SessionReplayNextJSInstructionsWrapper,
    [SDKKey.NUXT_JS]: SessionReplayNuxtJSInstructionsWrapper,
    [SDKKey.REACT]: SessionReplayReactInstructionsWrapper,
    [SDKKey.REACT_ROUTER]: SessionReplayReactRouterInstructionsWrapper,
    [SDKKey.REMIX]: SessionReplayRemixJSInstructionsWrapper,
    [SDKKey.TANSTACK_START]: SessionReplayReactInstructionsWrapper,
    [SDKKey.SVELTE]: SessionReplaySvelteInstructionsWrapper,
    [SDKKey.VITE]: SessionReplayReactInstructionsWrapper,
    [SDKKey.VUE_JS]: SessionReplayVueInstructionsWrapper,
    [SDKKey.WEBFLOW]: SessionReplayWebflowInstructionsWrapper,
    [SDKKey.IOS]: SessionReplayIOSInstructionsWrapper,
    [SDKKey.ANDROID]: SessionReplayAndroidInstructionsWrapper,
    [SDKKey.REACT_NATIVE]: SessionReplayRNInstructionsWrapper,
    [SDKKey.FLUTTER]: SessionReplayFlutterInstructionsWrapper,
}
