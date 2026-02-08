import {
    AndroidInstallation,
    AngularInstallation,
    AstroInstallation,
    BubbleInstallation,
    DocusaurusInstallation,
    FlutterInstallation,
    FramerInstallation,
    GoogleTagManagerInstallation,
    HTMLSnippetInstallation,
    IOSInstallation,
    JSWebInstallation,
    MobileFinalSteps,
    NextJSInstallation,
    NuxtInstallation,
    ReactInstallation,
    ReactNativeInstallation,
    RemixInstallation,
    ShopifyInstallation,
    SvelteInstallation,
    TanStackInstallation,
    VueInstallation,
    WebFinalSteps,
    WebflowInstallation,
    WordpressInstallation,
} from '@posthog/shared-onboarding/web-analytics'

import { SDKInstructionsMap, SDKKey } from '~/types'

import { withOnboardingDocsWrapper } from '../shared/onboardingWrappers'

// Snippet configurations for web analytics
const WEB_SNIPPETS = {
    WebFinalSteps,
}

const MOBILE_SNIPPETS = {
    MobileFinalSteps,
}

// JS Web SDKs
const WebAnalyticsJSWebInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: JSWebInstallation,
    snippets: WEB_SNIPPETS,
})
const WebAnalyticsHTMLSnippetInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: HTMLSnippetInstallation,
    snippets: WEB_SNIPPETS,
})

// Frontend frameworks
const WebAnalyticsReactInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ReactInstallation,
    snippets: WEB_SNIPPETS,
})
const WebAnalyticsNextJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NextJSInstallation,
    snippets: WEB_SNIPPETS,
})
const WebAnalyticsSvelteInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SvelteInstallation,
    snippets: WEB_SNIPPETS,
})
const WebAnalyticsAstroInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AstroInstallation,
    snippets: WEB_SNIPPETS,
})
const WebAnalyticsAngularInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AngularInstallation,
    snippets: WEB_SNIPPETS,
})
const WebAnalyticsVueInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: VueInstallation,
    snippets: WEB_SNIPPETS,
})
const WebAnalyticsNuxtJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NuxtInstallation,
    snippets: WEB_SNIPPETS,
})
const WebAnalyticsRemixJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: RemixInstallation,
    snippets: WEB_SNIPPETS,
})
const WebAnalyticsTanStackInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: TanStackInstallation,
    snippets: WEB_SNIPPETS,
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
})
const WebAnalyticsIOSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: IOSInstallation,
    snippets: MOBILE_SNIPPETS,
})
const WebAnalyticsFlutterInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: FlutterInstallation,
    snippets: MOBILE_SNIPPETS,
})
const WebAnalyticsRNInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ReactNativeInstallation,
    snippets: MOBILE_SNIPPETS,
})

export const WebAnalyticsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: WebAnalyticsJSWebInstructionsWrapper,
    [SDKKey.HTML_SNIPPET]: WebAnalyticsHTMLSnippetInstructionsWrapper,
    [SDKKey.ANGULAR]: WebAnalyticsAngularInstructionsWrapper,
    [SDKKey.ASTRO]: WebAnalyticsAstroInstructionsWrapper,
    [SDKKey.BUBBLE]: WebAnalyticsBubbleInstructionsWrapper,
    [SDKKey.DOCUSAURUS]: WebAnalyticsDocusaurusInstructionsWrapper,
    [SDKKey.FRAMER]: WebAnalyticsFramerInstructionsWrapper,
    [SDKKey.GOOGLE_TAG_MANAGER]: WebAnalyticsGoogleTagManagerInstructionsWrapper,
    [SDKKey.NEXT_JS]: WebAnalyticsNextJSInstructionsWrapper,
    [SDKKey.NUXT_JS]: WebAnalyticsNuxtJSInstructionsWrapper,
    [SDKKey.REACT]: WebAnalyticsReactInstructionsWrapper,
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
