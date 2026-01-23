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

import { AdvertiseMobileReplayContext } from '../session-replay/SessionReplaySDKInstructions'
import { withMobileReplay, withOnboardingDocsWrapper } from './onboardingWrappers'

// Default snippets for Product Analytics
// These are the base event capture snippets used by Installation components
const JS_WEB_SNIPPETS = { JSEventCapture }
const NODE_SNIPPETS = { NodeEventCapture }
const PYTHON_SNIPPETS = { PythonEventCapture }

// SDK configuration types
interface WebSDKConfig {
    Installation: React.ComponentType<any>
    snippets?: Record<string, React.ComponentType<any>>
    wizard?: string
}

interface MobileSDKConfig {
    Installation: React.ComponentType<any>
    wizard?: string
}

// Mobile SDKs, wrapped with AdvertiseMobileReplay component
const MobileSDKs: Partial<Record<SDKKey, MobileSDKConfig>> = {
    [SDKKey.ANDROID]: { Installation: AndroidInstallation },
    [SDKKey.IOS]: { Installation: IOSInstallation },
    [SDKKey.FLUTTER]: { Installation: FlutterInstallation },
    [SDKKey.REACT_NATIVE]: { Installation: ReactNativeInstallation, wizard: 'React Native' },
}

// Web/Server SDKs, default configurations from @posthog/shared-onboarding/product-analytics
const WebSDKs: Partial<Record<SDKKey, WebSDKConfig>> = {
    // JS Web
    [SDKKey.JS_WEB]: { Installation: JSWebInstallation, snippets: JS_WEB_SNIPPETS },
    [SDKKey.HTML_SNIPPET]: { Installation: HTMLSnippetInstallation, snippets: JS_WEB_SNIPPETS },

    // Frontend frameworks
    [SDKKey.REACT]: { Installation: ReactInstallation, snippets: JS_WEB_SNIPPETS, wizard: 'React' },
    [SDKKey.NEXT_JS]: { Installation: NextJSInstallation, snippets: JS_WEB_SNIPPETS, wizard: 'Next.js' },
    [SDKKey.SVELTE]: { Installation: SvelteInstallation, snippets: JS_WEB_SNIPPETS, wizard: 'Svelte' },
    [SDKKey.ASTRO]: { Installation: AstroInstallation, snippets: JS_WEB_SNIPPETS, wizard: 'Astro' },
    [SDKKey.TANSTACK_START]: { Installation: TanStackInstallation, snippets: JS_WEB_SNIPPETS },
    [SDKKey.ANGULAR]: { Installation: AngularInstallation, snippets: JS_WEB_SNIPPETS },
    [SDKKey.VUE_JS]: { Installation: VueInstallation, snippets: JS_WEB_SNIPPETS },
    [SDKKey.NUXT_JS]: { Installation: NuxtInstallation, snippets: JS_WEB_SNIPPETS },
    [SDKKey.REMIX]: { Installation: RemixInstallation, snippets: JS_WEB_SNIPPETS },
    [SDKKey.BUBBLE]: { Installation: BubbleInstallation, snippets: JS_WEB_SNIPPETS },
    [SDKKey.FRAMER]: { Installation: FramerInstallation, snippets: JS_WEB_SNIPPETS },
    [SDKKey.WEBFLOW]: { Installation: WebflowInstallation, snippets: JS_WEB_SNIPPETS },
    [SDKKey.DOCUSAURUS]: { Installation: DocusaurusInstallation },
    [SDKKey.GOOGLE_TAG_MANAGER]: { Installation: GoogleTagManagerInstallation, snippets: JS_WEB_SNIPPETS },

    // Server SDKs
    [SDKKey.NODE_JS]: { Installation: NodeJSInstallation, snippets: NODE_SNIPPETS },
    [SDKKey.PYTHON]: { Installation: PythonInstallation, snippets: PYTHON_SNIPPETS },
    [SDKKey.DJANGO]: { Installation: DjangoInstallation, snippets: PYTHON_SNIPPETS, wizard: 'Django' },
    [SDKKey.GO]: { Installation: GoInstallation },
    [SDKKey.PHP]: { Installation: PHPInstallation },
    [SDKKey.LARAVEL]: { Installation: LaravelInstallation },
    [SDKKey.RUBY]: { Installation: RubyInstallation },
    [SDKKey.ELIXIR]: { Installation: ElixirInstallation },

    // API
    [SDKKey.API]: { Installation: APIInstallation },

    // Integrations
    [SDKKey.SEGMENT]: { Installation: SegmentInstallation },
    [SDKKey.RUDDERSTACK]: { Installation: RudderstackInstallation },
    [SDKKey.SENTRY]: { Installation: SentryInstallation },
    [SDKKey.RETOOL]: { Installation: RetoolInstallation },
    [SDKKey.SHOPIFY]: { Installation: ShopifyInstallation },
    [SDKKey.WORDPRESS]: { Installation: WordpressInstallation },
    [SDKKey.ZAPIER]: { Installation: ZapierInstallation },
    [SDKKey.N8N]: { Installation: N8nInstallation },
    [SDKKey.MOENGAGE]: { Installation: MoEngageInstallation },

    // LLM integrations
    [SDKKey.HELICONE]: { Installation: HeliconeInstallation },
    [SDKKey.LANGFUSE]: { Installation: LangfuseInstallation },
    [SDKKey.TRACELOOP]: { Installation: TraceloopInstallation },
}

// SDK aliases, map one SDK key to another's configuration
const SDKAliases: Partial<Record<SDKKey, SDKKey>> = {
    [SDKKey.VITE]: SDKKey.REACT,
}

// Per-SDK customization for other products (ex: feature flags) to override defaults
interface SDKCustomization {
    Installation?: React.ComponentType<any>
    snippets?: Record<string, React.ComponentType<any>>
    wizard?: string
}

interface BuildInstructionsConfig {
    /** Context string for mobile replay ads */
    mobileContext?: AdvertiseMobileReplayContext
    /** Per-SDK customizations, override installation components or snippets for specific SDKs */
    sdkCustomizations?: Partial<Record<SDKKey, SDKCustomization>>
}

/** Builds an SDK instructions map for a product, using defaults from @posthog/shared-onboarding/product-analytics */
export function buildInstructions(keys: SDKKey[], config: BuildInstructionsConfig = {}): SDKInstructionsMap {
    const { mobileContext, sdkCustomizations } = config
    const map: SDKInstructionsMap = {}

    for (const key of keys) {
        // Resolve aliases
        const resolvedKey = SDKAliases[key] ?? key
        const customization = sdkCustomizations?.[key]

        // Check mobile SDKs first
        const mobileConfig = MobileSDKs[resolvedKey]
        if (mobileConfig) {
            if (!mobileContext) {
                console.warn(`Mobile SDK ${key} requires mobileContext parameter`)
                continue
            }
            map[key] = withMobileReplay({
                Installation: customization?.Installation ?? mobileConfig.Installation,
                sdkKey: resolvedKey,
                onboardingContext: mobileContext,
                snippets: customization?.snippets,
                wizardIntegrationName: customization?.wizard ?? mobileConfig.wizard,
            })
            continue
        }

        // Check web/server SDKs
        const webConfig = WebSDKs[resolvedKey]
        if (webConfig) {
            map[key] = withOnboardingDocsWrapper({
                Installation: customization?.Installation ?? webConfig.Installation,
                snippets: customization?.snippets ?? webConfig.snippets,
                wizardIntegrationName: customization?.wizard ?? webConfig.wizard,
            })
            continue
        }

        // Custom SDK provided by other products
        if (customization?.Installation) {
            map[key] = withOnboardingDocsWrapper({
                Installation: customization.Installation,
                snippets: customization.snippets,
                wizardIntegrationName: customization.wizard,
            })
            continue
        }

        console.warn(`Unknown SDK key: ${key}`)
    }

    return map
}
