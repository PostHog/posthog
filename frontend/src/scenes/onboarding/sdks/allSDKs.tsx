/**
 * SDK logos can be either:
 * - SVG/PNG files (imported as images) - for logos with fixed colors that don't need dark mode support
 * - TSX components (React.memo) - for logos that need Tailwind's `dark:fill-white` class to work,
 *   since CSS classes inside SVG files don't apply when rendered as <img> tags
 */
import { Logomark } from 'lib/brand/Logomark'

import { SDK, SDKKey, SDKTag } from '~/types'

import { AnthropicLogo } from './logos/AnthropicLogo'
import { AstroLogo } from './logos/AstroLogo'
import { BubbleLogo } from './logos/BubbleLogo'
import { FramerLogo } from './logos/FramerLogo'
import { IOSLogo } from './logos/IOSLogo'
import { LangChainLogo } from './logos/LangChainLogo'
import { OpenAILogo } from './logos/OpenAILogo'
import { RemixLogo } from './logos/RemixLogo'
import { RetoolLogo } from './logos/RetoolLogo'
import { RudderstackLogo } from './logos/RudderstackLogo'
import { SentryLogo } from './logos/SentryLogo'
import { VercelLogo } from './logos/VercelLogo'
import { WordpressLogo } from './logos/WordpressLogo'
import androidImage from './logos/android.svg'
import angularImage from './logos/angular.svg'
import djangoImage from './logos/django.svg'
import docusaurusImage from './logos/docusaurus.svg'
import elixirImage from './logos/elixir.svg'
import flutterImage from './logos/flutter.svg'
import gatsbyImage from './logos/gatsby.svg'
import geminiImage from './logos/gemini.svg'
import goImage from './logos/go.svg'
import gtmImage from './logos/gtm.svg'
import heliconeImage from './logos/helicone.svg'
import htmlImage from './logos/html.svg'
import javaImage from './logos/java.svg'
import jsImage from './logos/javascript_web.svg'
import langfuseImage from './logos/langfuse.svg'
import laravelImage from './logos/laravel.svg'
import litellmImage from './logos/litellm.png'
import moengageImage from './logos/moengage.png'
import n8nImage from './logos/n8n.svg'
import nextjsImage from './logos/nextjs.svg'
import nodejsImage from './logos/nodejs.svg'
import nuxtImage from './logos/nuxt.svg'
import openrouterImage from './logos/openrouter.png'
import phpImage from './logos/php.svg'
import pythonImage from './logos/python.svg'
import reactImage from './logos/react.svg'
import reactNativeImage from './logos/react.svg'
import rubyImage from './logos/ruby.svg'
import rustImage from './logos/rust.svg'
import segmentImage from './logos/segment.svg'
import shopifyImage from './logos/shopify.svg'
import svelteImage from './logos/svelte.svg'
import tanStackImage from './logos/tanstack.png'
import traceloopImage from './logos/traceloop.svg'
import viteImage from './logos/vite.svg'
import vueImage from './logos/vue.svg'
import webflowImage from './logos/webflow.svg'
import zapierImage from './logos/zapier.svg'

export const ALL_SDKS: SDK[] = [
    // Web
    {
        name: 'Next.js',
        key: SDKKey.NEXT_JS,
        tags: [SDKTag.WEB, SDKTag.SERVER, SDKTag.POPULAR],
        recommended: true,
        image: nextjsImage,
        docsLink: 'https://posthog.com/docs/libraries/next-js',
    },
    {
        name: 'HTML snippet',
        key: SDKKey.HTML_SNIPPET,
        recommended: true,
        tags: [SDKTag.POPULAR, SDKTag.WEB],
        image: htmlImage,
        docsLink: 'https://posthog.com/docs/libraries/js',
    },
    {
        name: 'JavaScript web',
        key: SDKKey.JS_WEB,
        recommended: true,
        tags: [SDKTag.POPULAR, SDKTag.WEB],
        image: jsImage,
        docsLink: 'https://posthog.com/docs/libraries/js',
    },
    {
        name: 'React',
        key: SDKKey.REACT,
        tags: [SDKTag.WEB, SDKTag.POPULAR],
        recommended: true,
        image: reactImage,
        docsLink: 'https://posthog.com/docs/libraries/react',
    },
    {
        name: 'React Native',
        key: SDKKey.REACT_NATIVE,
        tags: [SDKTag.MOBILE, SDKTag.POPULAR],
        recommended: true,
        image: reactNativeImage,
        docsLink: 'https://posthog.com/docs/libraries/react-native',
    },
    {
        name: 'Android',
        key: SDKKey.ANDROID,
        tags: [SDKTag.MOBILE],
        image: androidImage,
        docsLink: 'https://posthog.com/docs/libraries/android',
    },
    {
        name: 'Angular',
        key: SDKKey.ANGULAR,
        tags: [SDKTag.WEB],
        image: angularImage,
        docsLink: 'https://posthog.com/docs/libraries/angular',
    },
    {
        name: 'API',
        key: SDKKey.API,
        tags: [SDKTag.SERVER, SDKTag.INTEGRATION],
        image: (
            <span className="flex h-8 w-8">
                <Logomark />
            </span>
        ),
        docsLink: 'https://posthog.com/docs/api',
    },
    {
        name: 'Astro',
        key: SDKKey.ASTRO,
        tags: [SDKTag.WEB],
        image: <AstroLogo />,
        docsLink: 'https://posthog.com/docs/libraries/astro',
    },
    {
        name: 'Bubble',
        key: SDKKey.BUBBLE,
        tags: [SDKTag.WEB],
        image: <BubbleLogo />,
        docsLink: 'https://posthog.com/docs/libraries/bubble',
    },
    {
        name: 'Django',
        key: SDKKey.DJANGO,
        tags: [SDKTag.SERVER],
        image: djangoImage,
        docsLink: 'https://posthog.com/docs/libraries/django',
    },
    {
        name: 'Elixir',
        key: SDKKey.ELIXIR,
        tags: [SDKTag.SERVER],
        image: elixirImage,
        docsLink: 'https://posthog.com/docs/libraries/elixir',
    },
    {
        name: 'Flutter',
        key: SDKKey.FLUTTER,
        tags: [SDKTag.MOBILE],
        image: flutterImage,
        docsLink: 'https://posthog.com/docs/libraries/flutter',
    },
    {
        name: 'Framer',
        key: SDKKey.FRAMER,
        tags: [SDKTag.WEB],
        image: <FramerLogo />,
        docsLink: 'https://posthog.com/docs/libraries/framer',
    },
    {
        name: 'Gatsby',
        key: SDKKey.GATSBY,
        tags: [SDKTag.WEB],
        image: gatsbyImage,
        docsLink: 'https://posthog.com/docs/libraries/gatsby',
    },
    {
        name: 'Go',
        key: SDKKey.GO,
        tags: [SDKTag.SERVER],
        image: goImage,
        docsLink: 'https://posthog.com/docs/libraries/go',
    },
    {
        name: 'Helicone',
        key: SDKKey.HELICONE,
        tags: [SDKTag.LLM],
        image: heliconeImage,
        docsLink: 'https://posthog.com/docs/llm-analytics/integrations/helicone-posthog',
    },
    {
        name: 'OpenAI',
        key: SDKKey.OPENAI,
        tags: [SDKTag.LLM],
        image: <OpenAILogo />,
        docsLink: 'https://posthog.com/docs/llm-analytics/installation/openai',
    },
    {
        name: 'Anthropic',
        key: SDKKey.ANTHROPIC,
        tags: [SDKTag.LLM],
        image: <AnthropicLogo />,
        docsLink: 'https://posthog.com/docs/llm-analytics/installation/anthropic',
    },
    {
        name: 'Google Gemini',
        key: SDKKey.GOOGLE_GEMINI,
        tags: [],
        image: geminiImage,
        docsLink: 'https://posthog.com/docs/llm-analytics/installation/google',
    },
    {
        name: 'Vercel AI SDK',
        key: SDKKey.VERCEL_AI,
        tags: [],
        image: <VercelLogo />,
        docsLink: 'https://posthog.com/docs/llm-analytics/installation/vercel-ai',
    },
    {
        name: 'LangChain',
        key: SDKKey.LANGCHAIN,
        tags: [],
        image: <LangChainLogo />,
        docsLink: 'https://posthog.com/docs/llm-analytics/installation/langchain',
    },
    {
        name: 'LiteLLM',
        key: SDKKey.LITELLM,
        tags: [],
        image: litellmImage,
        docsLink: 'https://posthog.com/docs/llm-analytics/installation/litellm',
    },
    {
        name: 'OpenRouter',
        key: SDKKey.OPENROUTER,
        tags: [],
        image: openrouterImage,
        docsLink: 'https://posthog.com/docs/llm-analytics/installation/openrouter',
    },
    {
        name: 'Manual Capture',
        key: SDKKey.MANUAL_CAPTURE,
        tags: [],
        image: (
            <span className="flex w-8 pb-3">
                <Logomark />
            </span>
        ),
        docsLink: 'https://posthog.com/docs/llm-analytics/manual-capture',
    },
    {
        name: 'iOS',
        key: SDKKey.IOS,
        tags: [SDKTag.MOBILE],
        image: <IOSLogo />,
        docsLink: 'https://posthog.com/docs/libraries/ios',
    },
    {
        name: 'Java',
        key: SDKKey.JAVA,
        tags: [SDKTag.SERVER],
        image: javaImage,
        docsLink: 'https://posthog.com/docs/libraries/java',
    },
    {
        name: 'Langfuse',
        key: SDKKey.LANGFUSE,
        tags: [SDKTag.LLM],
        image: langfuseImage,
        docsLink: 'https://posthog.com/docs/llm-analytics/integrations/langfuse-posthog',
    },
    {
        name: 'Laravel',
        key: SDKKey.LARAVEL,
        tags: [SDKTag.SERVER],
        image: laravelImage,
        docsLink: 'https://posthog.com/docs/libraries/laravel',
    },
    {
        name: 'Node.js',
        key: SDKKey.NODE_JS,
        tags: [SDKTag.SERVER, SDKTag.POPULAR],
        recommended: true,
        image: nodejsImage,
        docsLink: 'https://posthog.com/docs/libraries/node',
    },
    {
        name: 'Nuxt.js',
        key: SDKKey.NUXT_JS,
        tags: [SDKTag.WEB, SDKTag.SERVER],
        image: nuxtImage,
        docsLink: 'https://posthog.com/docs/libraries/nuxt-js',
    },
    {
        name: 'PHP',
        key: SDKKey.PHP,
        tags: [SDKTag.SERVER],
        image: phpImage,
        docsLink: 'https://posthog.com/docs/libraries/php',
    },
    {
        name: 'Python',
        key: SDKKey.PYTHON,
        tags: [SDKTag.SERVER, SDKTag.POPULAR],
        recommended: true,
        image: pythonImage,
        docsLink: 'https://posthog.com/docs/libraries/python',
    },
    {
        name: 'Remix',
        key: SDKKey.REMIX,
        tags: [SDKTag.WEB],
        image: <RemixLogo />,
        docsLink: 'https://posthog.com/docs/libraries/remix',
    },
    {
        name: 'Ruby',
        key: SDKKey.RUBY,
        tags: [SDKTag.SERVER],
        image: rubyImage,
        docsLink: 'https://posthog.com/docs/libraries/ruby',
    },
    {
        name: 'Rust',
        key: SDKKey.RUST,
        tags: [SDKTag.SERVER],
        image: rustImage,
        docsLink: 'https://posthog.com/docs/libraries/rust',
    },
    {
        name: 'Svelte',
        key: SDKKey.SVELTE,
        tags: [SDKTag.WEB],
        image: svelteImage,
        docsLink: 'https://posthog.com/docs/libraries/svelte',
    },
    {
        name: 'TanStack Start',
        key: SDKKey.TANSTACK_START,
        tags: [SDKTag.WEB],
        image: tanStackImage,
        docsLink: 'https://posthog.com/docs/libraries/react',
    },
    {
        name: 'Traceloop',
        key: SDKKey.TRACELOOP,
        tags: [SDKTag.LLM],
        image: traceloopImage,
        docsLink: 'https://posthog.com/docs/llm-analytics/integrations/traceloop-posthog',
    },
    {
        name: 'Vite',
        key: SDKKey.VITE,
        tags: [SDKTag.WEB],
        image: viteImage,
        docsLink: 'https://posthog.com/docs/libraries/react',
    },
    {
        name: 'Vue.js',
        key: SDKKey.VUE_JS,
        tags: [SDKTag.WEB],
        image: vueImage,
        docsLink: 'https://posthog.com/docs/libraries/vue-js',
    },
    {
        name: 'Webflow',
        key: SDKKey.WEBFLOW,
        tags: [SDKTag.WEB],
        image: webflowImage,
        docsLink: 'https://posthog.com/docs/libraries/webflow',
    },
    // Integrations
    {
        name: 'Google Tag Manager',
        key: SDKKey.GOOGLE_TAG_MANAGER,
        tags: [SDKTag.WEB, SDKTag.INTEGRATION],
        image: gtmImage,
        docsLink: 'https://posthog.com/docs/libraries/google-tag-manager',
    },
    {
        name: 'Docusaurus',
        key: SDKKey.DOCUSAURUS,
        tags: [SDKTag.INTEGRATION],
        image: docusaurusImage,
        docsLink: 'https://posthog.com/docs/libraries/docusaurus',
    },
    {
        name: 'MoEngage',
        key: SDKKey.MOENGAGE,
        tags: [SDKTag.WEB, SDKTag.INTEGRATION],
        image: moengageImage,
        docsLink: 'https://posthog.com/docs/libraries/moengage',
    },
    {
        name: 'n8n',
        key: SDKKey.N8N,
        tags: [SDKTag.INTEGRATION],
        image: n8nImage,
        docsLink: 'https://posthog.com/docs/libraries/n8n',
    },
    {
        name: 'Segment',
        key: SDKKey.SEGMENT,
        tags: [SDKTag.INTEGRATION],
        image: segmentImage,
        docsLink: 'https://posthog.com/docs/libraries/segment',
    },
    {
        name: 'Sentry',
        key: SDKKey.SENTRY,
        tags: [SDKTag.INTEGRATION],
        image: <SentryLogo />,
        docsLink: 'https://posthog.com/docs/libraries/sentry',
    },
    {
        name: 'Shopify',
        key: SDKKey.SHOPIFY,
        tags: [SDKTag.INTEGRATION],
        image: shopifyImage,
        docsLink: 'https://posthog.com/docs/libraries/shopify',
    },
    {
        name: 'RudderStack',
        key: SDKKey.RUDDERSTACK,
        tags: [SDKTag.INTEGRATION],
        image: <RudderstackLogo />,
        docsLink: 'https://posthog.com/docs/libraries/rudderstack',
    },
    {
        name: 'Wordpress',
        key: SDKKey.WORDPRESS,
        tags: [SDKTag.INTEGRATION],
        image: <WordpressLogo />,
        docsLink: 'https://posthog.com/docs/libraries/wordpress',
    },
    {
        name: 'Retool',
        key: SDKKey.RETOOL,
        tags: [SDKTag.INTEGRATION],
        image: <RetoolLogo />,
        docsLink: 'https://posthog.com/docs/libraries/retool',
    },
    {
        name: 'Zapier',
        key: SDKKey.ZAPIER,
        tags: [SDKTag.INTEGRATION],
        image: zapierImage,
        docsLink: 'https://posthog.com/docs/libraries/zapier',
    },
]
