import {
    AndroidInstallation,
    AngularInstallation,
    AstroInstallation,
    BubbleInstallation,
    DocusaurusInstallation,
    FlutterInstallation,
    FramerInstallation,
    GoogleTagManagerInstallation,
    IOSInstallation,
    MobileFinalSteps,
    NextJSInstallation,
    NuxtInstallation,
    ReactInstallation,
    ReactNativeInstallation,
    ReactRouterInstallation,
    RemixInstallation,
    ShopifyInstallation,
    SvelteInstallation,
    TanStackInstallation,
    VueInstallation,
    WebFinalSteps,
    WebflowInstallation,
    WordpressInstallation,
    WebInstallation,
} from '@posthog/shared-onboarding/web-analytics'

import { SDKInstructionsMap, SDKKey } from '~/types'

import { JS_WEB_SNIPPETS } from '../shared/jsWebSnippets'
import { withOnboardingDocsWrapper } from '../shared/onboardingWrappers'

// Snippet configurations for web analytics
const WEB_SNIPPETS = {
    WebFinalSteps,
    ...JS_WEB_SNIPPETS,
}

const MOBILE_SNIPPETS = {
    MobileFinalSteps,
}

// JS Web SDKs
const WebAnalyticsWebInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: WebInstallation,
    snippets: WEB_SNIPPETS,
})

// Frontend frameworks
const WebAnalyticsReactInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ReactInstallation,
    snippets: WEB_SNIPPETS,
    wizardIntegrationName: 'React',
})
const WebAnalyticsNextJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NextJSInstallation,
    snippets: WEB_SNIPPETS,
    wizardIntegrationName: 'Next.js',
})
const WebAnalyticsSvelteInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SvelteInstallation,
    snippets: WEB_SNIPPETS,
    wizardIntegrationName: 'Svelte',
})
const WebAnalyticsAstroInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AstroInstallation,
    snippets: WEB_SNIPPETS,
    wizardIntegrationName: 'Astro',
})
const WebAnalyticsAngularInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AngularInstallation,
    snippets: WEB_SNIPPETS,
    wizardIntegrationName: 'Angular',
})
const WebAnalyticsVueInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: VueInstallation,
    snippets: WEB_SNIPPETS,
    wizardIntegrationName: 'Vue',
})
const WebAnalyticsNuxtJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NuxtInstallation,
    snippets: WEB_SNIPPETS,
    wizardIntegrationName: 'Nuxt',
})
const WebAnalyticsReactRouterInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ReactRouterInstallation,
    snippets: WEB_SNIPPETS,
})
const WebAnalyticsRemixJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: RemixInstallation,
    snippets: WEB_SNIPPETS,
    wizardIntegrationName: 'React Router',
})
const WebAnalyticsTanStackInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: TanStackInstallation,
    snippets: WEB_SNIPPETS,
    wizardIntegrationName: 'TanStack Start',
})

// Website builders
const WebAnalyticsBubbleInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: BubbleInstallation,
    snippets: WEB_SNIPPETS,
})
const WebAnalyticsFramerInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: FramerInstallation,
    snippets: WEB_SNIPPETS,
})
const WebAnalyticsWebflowInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: WebflowInstallation,
    snippets: WEB_SNIPPETS,
})
const WebAnalyticsDocusaurusInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: DocusaurusInstallation,
    snippets: WEB_SNIPPETS,
})
const WebAnalyticsGoogleTagManagerInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: GoogleTagManagerInstallation,
    snippets: WEB_SNIPPETS,
})
const WebAnalyticsShopifyInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ShopifyInstallation,
    snippets: WEB_SNIPPETS,
})
const WebAnalyticsWordpressInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: WordpressInstallation,
    snippets: WEB_SNIPPETS,
})

// Mobile SDKs
const WebAnalyticsAndroidInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AndroidInstallation,
    snippets: MOBILE_SNIPPETS,
    wizardIntegrationName: 'Android',
})
const WebAnalyticsIOSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: IOSInstallation,
    snippets: MOBILE_SNIPPETS,
    wizardIntegrationName: 'Swift',
})
const WebAnalyticsFlutterInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: FlutterInstallation,
    snippets: MOBILE_SNIPPETS,
})
const WebAnalyticsRNInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ReactNativeInstallation,
    snippets: MOBILE_SNIPPETS,
    wizardIntegrationName: 'React Native',
})

export const WebAnalyticsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: WebAnalyticsWebInstructionsWrapper,
    [SDKKey.ANGULAR]: WebAnalyticsAngularInstructionsWrapper,
    [SDKKey.ASTRO]: WebAnalyticsAstroInstructionsWrapper,
    [SDKKey.BUBBLE]: WebAnalyticsBubbleInstructionsWrapper,
    [SDKKey.DOCUSAURUS]: WebAnalyticsDocusaurusInstructionsWrapper,
    [SDKKey.FRAMER]: WebAnalyticsFramerInstructionsWrapper,
    [SDKKey.GOOGLE_TAG_MANAGER]: WebAnalyticsGoogleTagManagerInstructionsWrapper,
    [SDKKey.NEXT_JS]: WebAnalyticsNextJSInstructionsWrapper,
    [SDKKey.NUXT_JS]: WebAnalyticsNuxtJSInstructionsWrapper,
    [SDKKey.REACT]: WebAnalyticsReactInstructionsWrapper,
    [SDKKey.REACT_ROUTER]: WebAnalyticsReactRouterInstructionsWrapper,
    [SDKKey.REMIX]: WebAnalyticsRemixJSInstructionsWrapper,
    [SDKKey.SHOPIFY]: WebAnalyticsShopifyInstructionsWrapper,
    [SDKKey.SVELTE]: WebAnalyticsSvelteInstructionsWrapper,
    [SDKKey.TANSTACK_START]: WebAnalyticsTanStackInstructionsWrapper,
    [SDKKey.VITE]: WebAnalyticsReactInstructionsWrapper,
    [SDKKey.VUE_JS]: WebAnalyticsVueInstructionsWrapper,
    [SDKKey.WEBFLOW]: WebAnalyticsWebflowInstructionsWrapper,
    [SDKKey.WORDPRESS]: WebAnalyticsWordpressInstructionsWrapper,
    [SDKKey.ANDROID]: WebAnalyticsAndroidInstructionsWrapper,
    [SDKKey.FLUTTER]: WebAnalyticsFlutterInstructionsWrapper,
    [SDKKey.IOS]: WebAnalyticsIOSInstructionsWrapper,
    [SDKKey.REACT_NATIVE]: WebAnalyticsRNInstructionsWrapper,
}
