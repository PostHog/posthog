import {
    ProductAnalyticsAndroidInstructions,
    ProductAnalyticsAstroInstructions,
    ProductAnalyticsFlutterInstructions,
    ProductAnalyticsIOSInstructions,
    ProductAnalyticsNextJSInstructions,
    ProductAnalyticsRNInstructions,
    ProductAnalyticsReactInstructions,
    ProductAnalyticsSvelteJSInstructions,
    ProductAnalyticsTanStackInstructions,
} from '.'

import {
    APIInstallation,
    AngularInstallation,
    BubbleInstallation,
    DjangoInstallation,
    DocusaurusInstallation,
    ElixirInstallation,
    FramerInstallation,
    GoInstallation,
    GoogleTagManagerInstallation,
    HTMLSnippetInstallation,
    HeliconeInstallation,
    JSEventCapture,
    JSWebInstallation,
    LangfuseInstallation,
    LaravelInstallation,
    MoEngageInstallation,
    N8nInstallation,
    NodeEventCapture,
    NodeJSInstallation,
    NuxtInstallation,
    PHPInstallation,
    PythonEventCapture,
    PythonInstallation,
    RemixInstallation,
    RetoolInstallation,
    RubyInstallation,
    RudderstackInstallation,
    SegmentInstallation,
    SentryInstallation,
    ShopifyInstallation,
    TraceloopInstallation,
    VueInstallation,
    WebflowInstallation,
    WordpressInstallation,
    ZapierInstallation,
} from '@posthog/shared-onboarding/product-analytics'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { SDKInstructionsMap, SDKKey } from '~/types'

// Helper to create wrapped instruction components without recreating snippets on every render
function withOnboardingDocsWrapper(
    Installation: React.ComponentType,
    snippets?: Record<string, React.ComponentType<any>>
): () => JSX.Element {
    return function WrappedInstallation() {
        return (
            <OnboardingDocsContentWrapper snippets={snippets}>
                <Installation />
            </OnboardingDocsContentWrapper>
        )
    }
}

// Snippet configurations (defined once, not recreated on render)
const JS_WEB_SNIPPETS = {
    JSEventCapture,
}

const ANGULAR_SNIPPETS = {
    JSEventCapture,
}

const NODE_SNIPPETS = {
    NodeEventCapture,
}

const PYTHON_SNIPPETS = {
    PythonEventCapture,
}

const ProductAnalyticsAngularInstructionsWrapper = withOnboardingDocsWrapper(AngularInstallation, ANGULAR_SNIPPETS)
const ProductAnalyticsAPIInstructionsWrapper = withOnboardingDocsWrapper(APIInstallation)
const ProductAnalyticsBubbleInstructionsWrapper = withOnboardingDocsWrapper(BubbleInstallation, JS_WEB_SNIPPETS)
const ProductAnalyticsDjangoInstructionsWrapper = withOnboardingDocsWrapper(DjangoInstallation, PYTHON_SNIPPETS)
const ProductAnalyticsDocusaurusInstructionsWrapper = withOnboardingDocsWrapper(DocusaurusInstallation)
const ProductAnalyticsElixirInstructionsWrapper = withOnboardingDocsWrapper(ElixirInstallation)
const ProductAnalyticsFramerInstructionsWrapper = withOnboardingDocsWrapper(FramerInstallation, JS_WEB_SNIPPETS)
const ProductAnalyticsGoogleTagManagerInstructionsWrapper = withOnboardingDocsWrapper(
    GoogleTagManagerInstallation,
    JS_WEB_SNIPPETS
)
const ProductAnalyticsGoInstructionsWrapper = withOnboardingDocsWrapper(GoInstallation)
const ProductAnalyticsHeliconeInstructionsWrapper = withOnboardingDocsWrapper(HeliconeInstallation)
const ProductAnalyticsHTMLSnippetInstructionsWrapper = withOnboardingDocsWrapper(
    HTMLSnippetInstallation,
    JS_WEB_SNIPPETS
)
const ProductAnalyticsJSWebInstructionsWrapper = withOnboardingDocsWrapper(JSWebInstallation, JS_WEB_SNIPPETS)
const ProductAnalyticsLangfuseInstructionsWrapper = withOnboardingDocsWrapper(LangfuseInstallation)
const ProductAnalyticsLaravelInstructionsWrapper = withOnboardingDocsWrapper(LaravelInstallation)
const ProductAnalyticsMoEngageInstructionsWrapper = withOnboardingDocsWrapper(MoEngageInstallation)
const ProductAnalyticsN8nInstructionsWrapper = withOnboardingDocsWrapper(N8nInstallation)
const ProductAnalyticsNodeInstructionsWrapper = withOnboardingDocsWrapper(NodeJSInstallation, NODE_SNIPPETS)
const ProductAnalyticsNuxtJSInstructionsWrapper = withOnboardingDocsWrapper(NuxtInstallation, JS_WEB_SNIPPETS)
const ProductAnalyticsPHPInstructionsWrapper = withOnboardingDocsWrapper(PHPInstallation)
const ProductAnalyticsPythonInstructionsWrapper = withOnboardingDocsWrapper(PythonInstallation, PYTHON_SNIPPETS)
const ProductAnalyticsRemixJSInstructionsWrapper = withOnboardingDocsWrapper(RemixInstallation, JS_WEB_SNIPPETS)
const ProductAnalyticsRetoolInstructionsWrapper = withOnboardingDocsWrapper(RetoolInstallation)
const ProductAnalyticsRubyInstructionsWrapper = withOnboardingDocsWrapper(RubyInstallation)
const ProductAnalyticsRudderstackInstructionsWrapper = withOnboardingDocsWrapper(RudderstackInstallation)
const ProductAnalyticsSegmentInstructionsWrapper = withOnboardingDocsWrapper(SegmentInstallation)
const ProductAnalyticsSentryInstructionsWrapper = withOnboardingDocsWrapper(SentryInstallation)
const ProductAnalyticsShopifyInstructionsWrapper = withOnboardingDocsWrapper(ShopifyInstallation)
const ProductAnalyticsTraceloopInstructionsWrapper = withOnboardingDocsWrapper(TraceloopInstallation)
const ProductAnalyticsVueInstructionsWrapper = withOnboardingDocsWrapper(VueInstallation, JS_WEB_SNIPPETS)
const ProductAnalyticsWebflowInstructionsWrapper = withOnboardingDocsWrapper(WebflowInstallation, JS_WEB_SNIPPETS)
const ProductAnalyticsWordpressInstructionsWrapper = withOnboardingDocsWrapper(WordpressInstallation)
const ProductAnalyticsZapierInstructionsWrapper = withOnboardingDocsWrapper(ZapierInstallation)

// Wrap complex instruction components that have their own content
const ProductAnalyticsAndroidInstructionsWrapper = withOnboardingDocsWrapper(ProductAnalyticsAndroidInstructions)
const ProductAnalyticsIOSInstructionsWrapper = withOnboardingDocsWrapper(ProductAnalyticsIOSInstructions)
const ProductAnalyticsFlutterInstructionsWrapper = withOnboardingDocsWrapper(ProductAnalyticsFlutterInstructions)
const ProductAnalyticsRNInstructionsWrapper = withOnboardingDocsWrapper(ProductAnalyticsRNInstructions)
const ProductAnalyticsReactInstructionsWrapper = withOnboardingDocsWrapper(
    ProductAnalyticsReactInstructions,
    JS_WEB_SNIPPETS
)
const ProductAnalyticsNextJSInstructionsWrapper = withOnboardingDocsWrapper(
    ProductAnalyticsNextJSInstructions,
    JS_WEB_SNIPPETS
)
const ProductAnalyticsSvelteJSInstructionsWrapper = withOnboardingDocsWrapper(
    ProductAnalyticsSvelteJSInstructions,
    JS_WEB_SNIPPETS
)
const ProductAnalyticsAstroInstructionsWrapper = withOnboardingDocsWrapper(
    ProductAnalyticsAstroInstructions,
    JS_WEB_SNIPPETS
)
const ProductAnalyticsTanStackInstructionsWrapper = withOnboardingDocsWrapper(
    ProductAnalyticsTanStackInstructions,
    JS_WEB_SNIPPETS
)

export const ProductAnalyticsSDKInstructions: SDKInstructionsMap = {
    [SDKKey.JS_WEB]: ProductAnalyticsJSWebInstructionsWrapper,
    [SDKKey.ANDROID]: ProductAnalyticsAndroidInstructionsWrapper,
    [SDKKey.ANGULAR]: ProductAnalyticsAngularInstructionsWrapper,
    [SDKKey.REACT]: ProductAnalyticsReactInstructionsWrapper,
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
    [SDKKey.REACT_NATIVE]: ProductAnalyticsRNInstructionsWrapper,
    [SDKKey.REMIX]: ProductAnalyticsRemixJSInstructionsWrapper,
    [SDKKey.RETOOL]: ProductAnalyticsRetoolInstructionsWrapper,
    [SDKKey.RUBY]: ProductAnalyticsRubyInstructionsWrapper,
    [SDKKey.RUDDERSTACK]: ProductAnalyticsRudderstackInstructionsWrapper,
    [SDKKey.SEGMENT]: ProductAnalyticsSegmentInstructionsWrapper,
    [SDKKey.SENTRY]: ProductAnalyticsSentryInstructionsWrapper,
    [SDKKey.SHOPIFY]: ProductAnalyticsShopifyInstructionsWrapper,
    [SDKKey.SVELTE]: ProductAnalyticsSvelteJSInstructionsWrapper,
    [SDKKey.TANSTACK_START]: ProductAnalyticsTanStackInstructionsWrapper,
    [SDKKey.TRACELOOP]: ProductAnalyticsTraceloopInstructionsWrapper,
    [SDKKey.VITE]: ProductAnalyticsReactInstructionsWrapper,
    [SDKKey.VUE_JS]: ProductAnalyticsVueInstructionsWrapper,
    [SDKKey.WEBFLOW]: ProductAnalyticsWebflowInstructionsWrapper,
    [SDKKey.WORDPRESS]: ProductAnalyticsWordpressInstructionsWrapper,
    [SDKKey.ZAPIER]: ProductAnalyticsZapierInstructionsWrapper,
}
