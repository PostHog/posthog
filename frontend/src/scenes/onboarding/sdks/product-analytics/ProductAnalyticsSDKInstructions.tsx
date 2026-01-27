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
const ProductAnalyticsAndroidInstructionsWrapper = withMobileReplay({
    Installation: AndroidInstallation,
    sdkKey: SDKKey.ANDROID,
    onboardingContext: 'product-analytics-onboarding',
})
const ProductAnalyticsIOSInstructionsWrapper = withMobileReplay({
    Installation: IOSInstallation,
    sdkKey: SDKKey.IOS,
    onboardingContext: 'product-analytics-onboarding',
})
const ProductAnalyticsFlutterInstructionsWrapper = withMobileReplay({
    Installation: FlutterInstallation,
    sdkKey: SDKKey.FLUTTER,
    onboardingContext: 'product-analytics-onboarding',
})
const ProductAnalyticsRNInstructionsWrapper = withMobileReplay({
    Installation: ReactNativeInstallation,
    sdkKey: SDKKey.REACT_NATIVE,
    onboardingContext: 'product-analytics-onboarding',
    wizardIntegrationName: 'React Native',
})

// JS Web SDKs
const ProductAnalyticsJSWebInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: JSWebInstallation,
    snippets: JS_WEB_SNIPPETS,
})
const ProductAnalyticsHTMLSnippetInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: HTMLSnippetInstallation,
    snippets: JS_WEB_SNIPPETS,
})

// Frontend frameworks with wizard support where applicable
const ProductAnalyticsReactInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: ReactInstallation,
    snippets: JS_WEB_SNIPPETS,
    wizardIntegrationName: 'React',
})
const ProductAnalyticsNextJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NextJSInstallation,
    snippets: JS_WEB_SNIPPETS,
    wizardIntegrationName: 'Next.js',
})
const ProductAnalyticsSvelteInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: SvelteInstallation,
    snippets: JS_WEB_SNIPPETS,
    wizardIntegrationName: 'Svelte',
})
const ProductAnalyticsAstroInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AstroInstallation,
    snippets: JS_WEB_SNIPPETS,
    wizardIntegrationName: 'Astro',
})
const ProductAnalyticsTanStackInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: TanStackInstallation,
    snippets: JS_WEB_SNIPPETS,
})
const ProductAnalyticsAngularInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: AngularInstallation,
    snippets: JS_WEB_SNIPPETS,
})
const ProductAnalyticsVueInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: VueInstallation,
    snippets: JS_WEB_SNIPPETS,
})
const ProductAnalyticsNuxtJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NuxtInstallation,
    snippets: JS_WEB_SNIPPETS,
})
const ProductAnalyticsRemixJSInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: RemixInstallation,
    snippets: JS_WEB_SNIPPETS,
})
const ProductAnalyticsBubbleInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: BubbleInstallation,
    snippets: JS_WEB_SNIPPETS,
})
const ProductAnalyticsFramerInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: FramerInstallation,
    snippets: JS_WEB_SNIPPETS,
})
const ProductAnalyticsWebflowInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: WebflowInstallation,
    snippets: JS_WEB_SNIPPETS,
})
const ProductAnalyticsDocusaurusInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: DocusaurusInstallation,
})
const ProductAnalyticsGoogleTagManagerInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: GoogleTagManagerInstallation,
    snippets: JS_WEB_SNIPPETS,
})

// Server-side SDKs
const ProductAnalyticsNodeInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: NodeJSInstallation,
    snippets: NODE_SNIPPETS,
})
const ProductAnalyticsPythonInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: PythonInstallation,
    snippets: PYTHON_SNIPPETS,
})
const ProductAnalyticsDjangoInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: DjangoInstallation,
    snippets: PYTHON_SNIPPETS,
    wizardIntegrationName: 'Django',
})
const ProductAnalyticsGoInstructionsWrapper = withOnboardingDocsWrapper({ Installation: GoInstallation })
const ProductAnalyticsPHPInstructionsWrapper = withOnboardingDocsWrapper({ Installation: PHPInstallation })
const ProductAnalyticsLaravelInstructionsWrapper = withOnboardingDocsWrapper({ Installation: LaravelInstallation })
const ProductAnalyticsRubyInstructionsWrapper = withOnboardingDocsWrapper({ Installation: RubyInstallation })
const ProductAnalyticsElixirInstructionsWrapper = withOnboardingDocsWrapper({ Installation: ElixirInstallation })

// API
const ProductAnalyticsAPIInstructionsWrapper = withOnboardingDocsWrapper({ Installation: APIInstallation })

// Integrations
const ProductAnalyticsSegmentInstructionsWrapper = withOnboardingDocsWrapper({ Installation: SegmentInstallation })
const ProductAnalyticsRudderstackInstructionsWrapper = withOnboardingDocsWrapper({
    Installation: RudderstackInstallation,
})
const ProductAnalyticsSentryInstructionsWrapper = withOnboardingDocsWrapper({ Installation: SentryInstallation })
const ProductAnalyticsRetoolInstructionsWrapper = withOnboardingDocsWrapper({ Installation: RetoolInstallation })
const ProductAnalyticsShopifyInstructionsWrapper = withOnboardingDocsWrapper({ Installation: ShopifyInstallation })
const ProductAnalyticsWordpressInstructionsWrapper = withOnboardingDocsWrapper({ Installation: WordpressInstallation })
const ProductAnalyticsZapierInstructionsWrapper = withOnboardingDocsWrapper({ Installation: ZapierInstallation })
const ProductAnalyticsN8nInstructionsWrapper = withOnboardingDocsWrapper({ Installation: N8nInstallation })
const ProductAnalyticsMoEngageInstructionsWrapper = withOnboardingDocsWrapper({ Installation: MoEngageInstallation })

// LLM Integrations
const ProductAnalyticsHeliconeInstructionsWrapper = withOnboardingDocsWrapper({ Installation: HeliconeInstallation })
const ProductAnalyticsLangfuseInstructionsWrapper = withOnboardingDocsWrapper({ Installation: LangfuseInstallation })
const ProductAnalyticsTraceloopInstructionsWrapper = withOnboardingDocsWrapper({ Installation: TraceloopInstallation })

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
