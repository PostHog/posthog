import {
    APIInstallation,
    AndroidInstallation,
    AngularInstallation,
    AstroInstallation,
    BubbleInstallation,
    DjangoInstallation,
    DocusaurusInstallation,
    ElixirInstallation,
    FlutterInstallation,
    FramerInstallation,
    GoInstallation,
    GoogleTagManagerInstallation,
    HTMLSnippetInstallation,
    HeliconeInstallation,
    IOSInstallation,
    JSEventCapture,
    JSWebInstallation,
    LangfuseInstallation,
    LaravelInstallation,
    MoEngageInstallation,
    N8nInstallation,
    NextJSInstallation,
    NodeEventCapture,
    NodeJSInstallation,
    NuxtInstallation,
    PHPInstallation,
    PythonEventCapture,
    PythonInstallation,
    ReactInstallation,
    ReactNativeInstallation,
    RemixInstallation,
    RetoolInstallation,
    RubyInstallation,
    RudderstackInstallation,
    SegmentInstallation,
    SentryInstallation,
    ShopifyInstallation,
    SvelteInstallation,
    TanStackInstallation,
    TraceloopInstallation,
    VueInstallation,
    WebflowInstallation,
    WordpressInstallation,
    ZapierInstallation,
} from '@posthog/shared-onboarding/product-analytics'

import { SDKInstructionsMap, SDKKey } from '~/types'

import { withMobileReplay, withOnboardingDocsWrapper } from '../shared/onboardingWrappers'

// Snippet configurations (defined once, not recreated on render)
const JS_WEB_SNIPPETS = {
    JSEventCapture,
}

const NODE_SNIPPETS = {
    NodeEventCapture,
}

const PYTHON_SNIPPETS = {
    PythonEventCapture,
}

// Mobile SDKs with AdvertiseMobileReplay
const ProductAnalyticsAndroidInstructionsWrapper = withMobileReplay(
    AndroidInstallation,
    SDKKey.ANDROID,
    'product-analytics-onboarding'
)
const ProductAnalyticsIOSInstructionsWrapper = withMobileReplay(
    IOSInstallation,
    SDKKey.IOS,
    'product-analytics-onboarding'
)
const ProductAnalyticsFlutterInstructionsWrapper = withMobileReplay(
    FlutterInstallation,
    SDKKey.FLUTTER,
    'product-analytics-onboarding'
)
const ProductAnalyticsRNInstructionsWrapper = withMobileReplay(
    ReactNativeInstallation,
    SDKKey.REACT_NATIVE,
    'product-analytics-onboarding',
    undefined,
    'React Native'
)

// JS Web SDKs
const ProductAnalyticsJSWebInstructionsWrapper = withOnboardingDocsWrapper(JSWebInstallation, JS_WEB_SNIPPETS)
const ProductAnalyticsHTMLSnippetInstructionsWrapper = withOnboardingDocsWrapper(
    HTMLSnippetInstallation,
    JS_WEB_SNIPPETS
)

// Frontend frameworks with wizard support where applicable
const ProductAnalyticsReactInstructionsWrapper = withOnboardingDocsWrapper(ReactInstallation, JS_WEB_SNIPPETS, 'React')
const ProductAnalyticsNextJSInstructionsWrapper = withOnboardingDocsWrapper(
    NextJSInstallation,
    JS_WEB_SNIPPETS,
    'Next.js'
)
const ProductAnalyticsSvelteInstructionsWrapper = withOnboardingDocsWrapper(
    SvelteInstallation,
    JS_WEB_SNIPPETS,
    'Svelte'
)
const ProductAnalyticsAstroInstructionsWrapper = withOnboardingDocsWrapper(AstroInstallation, JS_WEB_SNIPPETS, 'Astro')
const ProductAnalyticsTanStackInstructionsWrapper = withOnboardingDocsWrapper(TanStackInstallation, JS_WEB_SNIPPETS)
const ProductAnalyticsAngularInstructionsWrapper = withOnboardingDocsWrapper(AngularInstallation, JS_WEB_SNIPPETS)
const ProductAnalyticsVueInstructionsWrapper = withOnboardingDocsWrapper(VueInstallation, JS_WEB_SNIPPETS)
const ProductAnalyticsNuxtJSInstructionsWrapper = withOnboardingDocsWrapper(NuxtInstallation, JS_WEB_SNIPPETS)
const ProductAnalyticsRemixJSInstructionsWrapper = withOnboardingDocsWrapper(RemixInstallation, JS_WEB_SNIPPETS)
const ProductAnalyticsBubbleInstructionsWrapper = withOnboardingDocsWrapper(BubbleInstallation, JS_WEB_SNIPPETS)
const ProductAnalyticsFramerInstructionsWrapper = withOnboardingDocsWrapper(FramerInstallation, JS_WEB_SNIPPETS)
const ProductAnalyticsWebflowInstructionsWrapper = withOnboardingDocsWrapper(WebflowInstallation, JS_WEB_SNIPPETS)
const ProductAnalyticsDocusaurusInstructionsWrapper = withOnboardingDocsWrapper(DocusaurusInstallation)
const ProductAnalyticsGoogleTagManagerInstructionsWrapper = withOnboardingDocsWrapper(
    GoogleTagManagerInstallation,
    JS_WEB_SNIPPETS
)

// Server-side SDKs
const ProductAnalyticsNodeInstructionsWrapper = withOnboardingDocsWrapper(NodeJSInstallation, NODE_SNIPPETS)
const ProductAnalyticsPythonInstructionsWrapper = withOnboardingDocsWrapper(PythonInstallation, PYTHON_SNIPPETS)
const ProductAnalyticsDjangoInstructionsWrapper = withOnboardingDocsWrapper(
    DjangoInstallation,
    PYTHON_SNIPPETS,
    'Django'
)
const ProductAnalyticsGoInstructionsWrapper = withOnboardingDocsWrapper(GoInstallation)
const ProductAnalyticsPHPInstructionsWrapper = withOnboardingDocsWrapper(PHPInstallation)
const ProductAnalyticsLaravelInstructionsWrapper = withOnboardingDocsWrapper(LaravelInstallation)
const ProductAnalyticsRubyInstructionsWrapper = withOnboardingDocsWrapper(RubyInstallation)
const ProductAnalyticsElixirInstructionsWrapper = withOnboardingDocsWrapper(ElixirInstallation)

// API
const ProductAnalyticsAPIInstructionsWrapper = withOnboardingDocsWrapper(APIInstallation)

// Integrations
const ProductAnalyticsSegmentInstructionsWrapper = withOnboardingDocsWrapper(SegmentInstallation)
const ProductAnalyticsRudderstackInstructionsWrapper = withOnboardingDocsWrapper(RudderstackInstallation)
const ProductAnalyticsSentryInstructionsWrapper = withOnboardingDocsWrapper(SentryInstallation)
const ProductAnalyticsRetoolInstructionsWrapper = withOnboardingDocsWrapper(RetoolInstallation)
const ProductAnalyticsShopifyInstructionsWrapper = withOnboardingDocsWrapper(ShopifyInstallation)
const ProductAnalyticsWordpressInstructionsWrapper = withOnboardingDocsWrapper(WordpressInstallation)
const ProductAnalyticsZapierInstructionsWrapper = withOnboardingDocsWrapper(ZapierInstallation)
const ProductAnalyticsN8nInstructionsWrapper = withOnboardingDocsWrapper(N8nInstallation)
const ProductAnalyticsMoEngageInstructionsWrapper = withOnboardingDocsWrapper(MoEngageInstallation)

// LLM Integrations
const ProductAnalyticsHeliconeInstructionsWrapper = withOnboardingDocsWrapper(HeliconeInstallation)
const ProductAnalyticsLangfuseInstructionsWrapper = withOnboardingDocsWrapper(LangfuseInstallation)
const ProductAnalyticsTraceloopInstructionsWrapper = withOnboardingDocsWrapper(TraceloopInstallation)

export const ProductAnalyticsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: ProductAnalyticsJSWebInstructionsWrapper,
    [SDKKey.ANDROID]: ProductAnalyticsAndroidInstructionsWrapper,
    [SDKKey.ANGULAR]: ProductAnalyticsAngularInstructionsWrapper,
    [SDKKey.API]: ProductAnalyticsAPIInstructionsWrapper,
    [SDKKey.ASTRO]: ProductAnalyticsAstroInstructionsWrapper,
    [SDKKey.BUBBLE]: ProductAnalyticsBubbleInstructionsWrapper,
    [SDKKey.DJANGO]: ProductAnalyticsDjangoInstructionsWrapper,
    [SDKKey.DOCUSAURUS]: ProductAnalyticsDocusaurusInstructionsWrapper,
    [SDKKey.ELIXIR]: ProductAnalyticsElixirInstructionsWrapper,
    [SDKKey.FLUTTER]: ProductAnalyticsFlutterInstructionsWrapper,
    [SDKKey.FRAMER]: ProductAnalyticsFramerInstructionsWrapper,
    [SDKKey.GO]: ProductAnalyticsGoInstructionsWrapper,
    [SDKKey.GOOGLE_TAG_MANAGER]: ProductAnalyticsGoogleTagManagerInstructionsWrapper,
    [SDKKey.HELICONE]: ProductAnalyticsHeliconeInstructionsWrapper,
    [SDKKey.HTML_SNIPPET]: ProductAnalyticsHTMLSnippetInstructionsWrapper,
    [SDKKey.IOS]: ProductAnalyticsIOSInstructionsWrapper,
    [SDKKey.LANGFUSE]: ProductAnalyticsLangfuseInstructionsWrapper,
    [SDKKey.LARAVEL]: ProductAnalyticsLaravelInstructionsWrapper,
    [SDKKey.MOENGAGE]: ProductAnalyticsMoEngageInstructionsWrapper,
    [SDKKey.N8N]: ProductAnalyticsN8nInstructionsWrapper,
    [SDKKey.NEXT_JS]: ProductAnalyticsNextJSInstructionsWrapper,
    [SDKKey.NODE_JS]: ProductAnalyticsNodeInstructionsWrapper,
    [SDKKey.NUXT_JS]: ProductAnalyticsNuxtJSInstructionsWrapper,
    [SDKKey.PHP]: ProductAnalyticsPHPInstructionsWrapper,
    [SDKKey.PYTHON]: ProductAnalyticsPythonInstructionsWrapper,
    [SDKKey.REACT]: ProductAnalyticsReactInstructionsWrapper,
    [SDKKey.REACT_NATIVE]: ProductAnalyticsRNInstructionsWrapper,
    [SDKKey.REMIX]: ProductAnalyticsRemixJSInstructionsWrapper,
    [SDKKey.RETOOL]: ProductAnalyticsRetoolInstructionsWrapper,
    [SDKKey.RUBY]: ProductAnalyticsRubyInstructionsWrapper,
    [SDKKey.RUDDERSTACK]: ProductAnalyticsRudderstackInstructionsWrapper,
    [SDKKey.SEGMENT]: ProductAnalyticsSegmentInstructionsWrapper,
    [SDKKey.SENTRY]: ProductAnalyticsSentryInstructionsWrapper,
    [SDKKey.SHOPIFY]: ProductAnalyticsShopifyInstructionsWrapper,
    [SDKKey.SVELTE]: ProductAnalyticsSvelteInstructionsWrapper,
    [SDKKey.TANSTACK_START]: ProductAnalyticsTanStackInstructionsWrapper,
    [SDKKey.TRACELOOP]: ProductAnalyticsTraceloopInstructionsWrapper,
    [SDKKey.VITE]: ProductAnalyticsReactInstructionsWrapper,
    [SDKKey.VUE_JS]: ProductAnalyticsVueInstructionsWrapper,
    [SDKKey.WEBFLOW]: ProductAnalyticsWebflowInstructionsWrapper,
    [SDKKey.WORDPRESS]: ProductAnalyticsWordpressInstructionsWrapper,
    [SDKKey.ZAPIER]: ProductAnalyticsZapierInstructionsWrapper,
}
