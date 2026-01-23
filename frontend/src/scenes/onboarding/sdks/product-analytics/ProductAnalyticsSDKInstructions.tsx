import { SDKKey } from '~/types'

import { buildInstructions } from '../shared/sdkWrappers'

export const ProductAnalyticsSDKInstructions = buildInstructions(
    [
        // Mobile
        SDKKey.ANDROID,
        SDKKey.IOS,
        SDKKey.FLUTTER,
        SDKKey.REACT_NATIVE,

        // JS Web
        SDKKey.JS_WEB,
        SDKKey.HTML_SNIPPET,

        // Frontend frameworks
        SDKKey.REACT,
        SDKKey.NEXT_JS,
        SDKKey.SVELTE,
        SDKKey.ASTRO,
        SDKKey.TANSTACK_START,
        SDKKey.ANGULAR,
        SDKKey.VUE_JS,
        SDKKey.NUXT_JS,
        SDKKey.REMIX,
        SDKKey.BUBBLE,
        SDKKey.FRAMER,
        SDKKey.WEBFLOW,
        SDKKey.DOCUSAURUS,
        SDKKey.GOOGLE_TAG_MANAGER,

        // Server
        SDKKey.NODE_JS,
        SDKKey.PYTHON,
        SDKKey.DJANGO,
        SDKKey.GO,
        SDKKey.PHP,
        SDKKey.LARAVEL,
        SDKKey.RUBY,
        SDKKey.ELIXIR,

        // API
        SDKKey.API,

        // Integrations
        SDKKey.SEGMENT,
        SDKKey.RUDDERSTACK,
        SDKKey.SENTRY,
        SDKKey.RETOOL,
        SDKKey.SHOPIFY,
        SDKKey.WORDPRESS,
        SDKKey.ZAPIER,
        SDKKey.N8N,
        SDKKey.MOENGAGE,

        // LLM Integrations
        SDKKey.HELICONE,
        SDKKey.LANGFUSE,
        SDKKey.TRACELOOP,

        // Alias
        SDKKey.VITE,
    ],
    { mobileContext: 'product-analytics-onboarding' }
)
