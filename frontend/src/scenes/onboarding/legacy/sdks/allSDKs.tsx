/**
 * SDK logos can be either:
 * - Cloudinary URLs (string) - preferred, for logos hosted on Cloudinary CDN
 * - SVG/PNG files (imported as images) - for logos not yet on Cloudinary
 * - TSX components (React.memo) - for logos that need Tailwind's `dark:fill-white` class to work,
 *   since CSS classes inside SVG files don't apply when rendered as <img> tags
 */
import { Logomark } from 'lib/brand'

import { SDK, SDKKey, SDKTag } from '~/types'

import androidImage from '../../shared/logos/android.svg'
import angularImage from '../../shared/logos/angular.svg'
import { AnthropicLogo } from '../../shared/logos/AnthropicLogo'
import { AstroLogo } from '../../shared/logos/AstroLogo'
import { BubbleLogo } from '../../shared/logos/BubbleLogo'
import djangoImage from '../../shared/logos/django.svg'
import docusaurusImage from '../../shared/logos/docusaurus.svg'
import dotnetImage from '../../shared/logos/dotnet.svg'
import elixirImage from '../../shared/logos/elixir.svg'
import flutterImage from '../../shared/logos/flutter.svg'
import { FramerLogo } from '../../shared/logos/FramerLogo'
import gatsbyImage from '../../shared/logos/gatsby.svg'
import geminiImage from '../../shared/logos/gemini.svg'
import goImage from '../../shared/logos/go.svg'
import gtmImage from '../../shared/logos/gtm.svg'
import honoImage from '../../shared/logos/hono.svg'
import { IOSLogo } from '../../shared/logos/IOSLogo'
import javaImage from '../../shared/logos/java.svg'
import jsImage from '../../shared/logos/javascript_web.svg'
import { LangChainLogo } from '../../shared/logos/LangChainLogo'
import langfuseImage from '../../shared/logos/langfuse.svg'
import laravelImage from '../../shared/logos/laravel.svg'
import moengageImage from '../../shared/logos/moengage.png'
import n8nImage from '../../shared/logos/n8n.svg'
import nextjsImage from '../../shared/logos/nextjs.svg'
import nodejsImage from '../../shared/logos/nodejs.svg'
import nuxtImage from '../../shared/logos/nuxt.svg'
import { OpenAILogo } from '../../shared/logos/OpenAILogo'
import { OpenRouterLogo } from '../../shared/logos/OpenRouterLogo'
import phpImage from '../../shared/logos/php.svg'
import pythonImage from '../../shared/logos/python.svg'
import railsImage from '../../shared/logos/rails.svg'
import reactImage from '../../shared/logos/react.svg'
import reactNativeImage from '../../shared/logos/react.svg'
import { ReactRouterLogo } from '../../shared/logos/ReactRouterLogo'
import { RemixLogo } from '../../shared/logos/RemixLogo'
import { RetoolLogo } from '../../shared/logos/RetoolLogo'
import rubyImage from '../../shared/logos/ruby.svg'
import { RudderstackLogo } from '../../shared/logos/RudderstackLogo'
import rustImage from '../../shared/logos/rust.svg'
import segmentImage from '../../shared/logos/segment.svg'
import { SentryLogo } from '../../shared/logos/SentryLogo'
import shopifyImage from '../../shared/logos/shopify.svg'
import svelteImage from '../../shared/logos/svelte.svg'
import tanStackImage from '../../shared/logos/tanstack.png'
import traceloopImage from '../../shared/logos/traceloop.svg'
import viteImage from '../../shared/logos/vite.svg'
import vueImage from '../../shared/logos/vue.svg'
import webflowImage from '../../shared/logos/webflow.svg'
import { WordpressLogo } from '../../shared/logos/WordpressLogo'
import zapierImage from '../../shared/logos/zapier.svg'

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
        name: 'Web',
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
                <Logomark className="w-8 h-auto" />
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
        name: '.NET',
        key: SDKKey.DOTNET,
        tags: [SDKTag.SERVER],
        image: dotnetImage,
        docsLink: 'https://posthog.com/docs/libraries/dotnet',
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
        name: 'Hono',
        key: SDKKey.HONO,
        tags: [SDKTag.SERVER],
        image: honoImage,
        docsLink: 'https://posthog.com/docs/libraries/hono',
    },
    {
        name: 'OpenAI',
        key: SDKKey.OPENAI,
        tags: [SDKTag.MODEL_PROVIDER, SDKTag.FRAMEWORK],
        image: <OpenAILogo />,
        docsLink: 'https://posthog.com/docs/ai-observability/installation/openai',
    },
    {
        name: 'OpenAI Agents',
        key: SDKKey.OPENAI_AGENTS,
        tags: [SDKTag.FRAMEWORK],
        image: <OpenAILogo />,
        docsLink: 'https://posthog.com/docs/ai-observability/installation/openai-agents',
    },
    {
        name: 'Anthropic',
        key: SDKKey.ANTHROPIC,
        tags: [SDKTag.MODEL_PROVIDER],
        image: <AnthropicLogo />,
        docsLink: 'https://posthog.com/docs/ai-observability/installation/anthropic',
    },
    {
        name: 'Google Gemini',
        key: SDKKey.GOOGLE_GEMINI,
        tags: [SDKTag.MODEL_PROVIDER],
        image: geminiImage,
        docsLink: 'https://posthog.com/docs/ai-observability/installation/google',
    },
    {
        name: 'Vercel AI SDK',
        key: SDKKey.VERCEL_AI,
        tags: [SDKTag.FRAMEWORK],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/vercel_373fa70879.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/vercel-ai',
    },
    {
        name: 'LangChain',
        key: SDKKey.LANGCHAIN,
        tags: [SDKTag.FRAMEWORK],
        image: <LangChainLogo />,
        docsLink: 'https://posthog.com/docs/ai-observability/installation/langchain',
    },
    {
        name: 'LiteLLM',
        key: SDKKey.LITELLM,
        tags: [SDKTag.FRAMEWORK, SDKTag.GATEWAY],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/litellmicon_a2805d75e5.png',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/litellm',
    },
    {
        name: 'OpenRouter',
        key: SDKKey.OPENROUTER,
        tags: [SDKTag.GATEWAY],
        image: <OpenRouterLogo />,
        docsLink: 'https://posthog.com/docs/ai-observability/installation/openrouter',
    },
    {
        name: 'Cloudflare AI Gateway',
        key: SDKKey.CLOUDFLARE_AI_GATEWAY,
        tags: [SDKTag.GATEWAY],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/cloudflare_logo_6572a9f441.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/cloudflare-ai-gateway',
    },
    {
        name: 'Dedalus Labs',
        key: SDKKey.DEDALUS,
        tags: [SDKTag.GATEWAY],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/dedalus_labs_logo_e03bb97137.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/dedalus',
    },
    {
        name: 'DeepSeek',
        key: SDKKey.DEEPSEEK,
        tags: [SDKTag.MODEL_PROVIDER],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/deepseek_df02608124.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/deepseek',
    },
    {
        name: 'LangGraph',
        key: SDKKey.LANGGRAPH,
        tags: [SDKTag.FRAMEWORK],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/langgraph_2f91869ac8.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/langgraph',
    },
    {
        name: 'Ollama',
        key: SDKKey.OLLAMA,
        tags: [SDKTag.MODEL_PROVIDER],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/ollama_ff56896a1f.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/ollama',
    },
    {
        name: 'AWS Bedrock',
        key: SDKKey.AWS_BEDROCK,
        tags: [SDKTag.MODEL_PROVIDER],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/bedrock_5c06698148.png',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/aws-bedrock',
    },
    {
        name: 'Azure OpenAI',
        key: SDKKey.AZURE_OPENAI,
        tags: [SDKTag.MODEL_PROVIDER],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/azure_openai_884ba0124a.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/azure-openai',
    },
    {
        name: 'Groq',
        key: SDKKey.GROQ,
        tags: [SDKTag.MODEL_PROVIDER],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/groq_a0ed539e47.png',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/groq',
    },
    {
        name: 'Mistral',
        key: SDKKey.MISTRAL,
        tags: [SDKTag.MODEL_PROVIDER],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/mistral_551c75e2dd.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/mistral',
    },
    {
        name: 'LlamaIndex',
        key: SDKKey.LLAMAINDEX,
        tags: [SDKTag.FRAMEWORK],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/llamaindex_f831132d7c.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/llamaindex',
    },
    {
        name: 'CrewAI',
        key: SDKKey.CREWAI,
        tags: [SDKTag.FRAMEWORK],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/crewai_67ee9f5eb6.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/crewai',
    },
    {
        name: 'Instructor',
        key: SDKKey.INSTRUCTOR,
        tags: [SDKTag.FRAMEWORK],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/instructor_b1982d9ce9.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/instructor',
    },
    {
        name: 'Pydantic AI',
        key: SDKKey.PYDANTIC_AI,
        tags: [SDKTag.FRAMEWORK],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/pydantic_ai_55029bc39b.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/pydantic-ai',
    },
    {
        name: 'xAI',
        key: SDKKey.XAI,
        tags: [SDKTag.MODEL_PROVIDER],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/xai_77b917714b.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/xai',
    },
    {
        name: 'Perplexity',
        key: SDKKey.PERPLEXITY,
        tags: [SDKTag.MODEL_PROVIDER],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/perplexity_7d451cb62c.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/perplexity',
    },
    {
        name: 'Together AI',
        key: SDKKey.TOGETHER_AI,
        tags: [SDKTag.MODEL_PROVIDER],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/together_ai_49ac1a57fb.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/together-ai',
    },
    {
        name: 'Fireworks AI',
        key: SDKKey.FIREWORKS_AI,
        tags: [SDKTag.MODEL_PROVIDER],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/fireworks_ai_a3d8a59e96.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/fireworks-ai',
    },
    {
        name: 'Cohere',
        key: SDKKey.COHERE,
        tags: [SDKTag.MODEL_PROVIDER],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/cohere_0ddf02d545.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/cohere',
    },
    {
        name: 'Hugging Face',
        key: SDKKey.HUGGING_FACE,
        tags: [SDKTag.MODEL_PROVIDER],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/hugging_face_ae0a406f62.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/hugging-face',
    },
    {
        name: 'DSPy',
        key: SDKKey.DSPY,
        tags: [SDKTag.FRAMEWORK],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/dspy_548bc2f255.webp',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/dspy',
    },
    {
        name: 'AutoGen',
        key: SDKKey.AUTOGEN,
        tags: [SDKTag.FRAMEWORK],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/autogen_a8c56d013e.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/autogen',
    },
    {
        name: 'Semantic Kernel',
        key: SDKKey.SEMANTIC_KERNEL,
        tags: [SDKTag.FRAMEWORK],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/w_200,c_limit,q_auto,f_auto/semantic_kernel_5102489978.png',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/semantic-kernel',
    },
    {
        name: 'smolagents',
        key: SDKKey.SMOLAGENTS,
        tags: [SDKTag.FRAMEWORK],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/smolagents_logo_1_545072ae17.png',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/smolagents',
    },
    {
        name: 'Mastra',
        key: SDKKey.MASTRA,
        tags: [SDKTag.FRAMEWORK],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/mastra_7ea7df92ab.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/mastra',
    },
    {
        name: 'Mirascope',
        key: SDKKey.MIRASCOPE,
        tags: [SDKTag.FRAMEWORK],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/mirascope_33f38e04ea.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/mirascope',
    },
    {
        name: 'Convex',
        key: SDKKey.CONVEX,
        tags: [SDKTag.FRAMEWORK],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/convex_d8dcddcd63.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/convex',
    },
    {
        name: 'Cerebras',
        key: SDKKey.CEREBRAS,
        tags: [SDKTag.MODEL_PROVIDER],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/cerebras_4d953c1c2b.png',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/cerebras',
    },
    {
        name: 'Vercel AI Gateway',
        key: SDKKey.VERCEL_AI_GATEWAY,
        tags: [SDKTag.GATEWAY],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/vercel_373fa70879.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/vercel-ai-gateway',
    },
    {
        name: 'Portkey',
        key: SDKKey.PORTKEY,
        tags: [SDKTag.GATEWAY],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/portkey_15a83f0395.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/portkey',
    },
    {
        name: 'Helicone',
        key: SDKKey.HELICONE,
        tags: [SDKTag.LLM, SDKTag.GATEWAY],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/helicone_7c41fa4c2d.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/helicone',
    },
    {
        name: 'Manual Capture',
        key: SDKKey.MANUAL_CAPTURE,
        tags: [SDKTag.FRAMEWORK, SDKTag.MODEL_PROVIDER, SDKTag.GATEWAY],
        image: (
            <span className="flex w-8 pb-3">
                <Logomark className="w-8 h-auto" />
            </span>
        ),
        docsLink: 'https://posthog.com/docs/ai-observability/installation/manual-capture',
    },
    {
        name: 'OpenTelemetry',
        key: SDKKey.OPENTELEMETRY,
        tags: [SDKTag.INTEGRATION],
        image: 'https://res.cloudinary.com/dmukukwp6/image/upload/opentelemetry_afb29df5ab.svg',
        docsLink: 'https://posthog.com/docs/ai-observability/installation/opentelemetry',
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
        docsLink: 'https://posthog.com/docs/ai-observability/integrations/langfuse-posthog',
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
        name: 'Nuxt.js 3.7+',
        key: SDKKey.NUXT_JS,
        tags: [SDKTag.WEB, SDKTag.SERVER],
        image: nuxtImage,
        docsLink: 'https://posthog.com/docs/libraries/nuxt-js',
    },
    {
        name: 'Nuxt.js 3.6 and below',
        key: SDKKey.NUXT_JS_36,
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
        name: 'React Router',
        key: SDKKey.REACT_ROUTER,
        tags: [SDKTag.WEB],
        searchTerms: ['remix'],
        image: <ReactRouterLogo />,
        docsLink: 'https://posthog.com/docs/libraries/react-router',
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
        name: 'Ruby on Rails',
        key: SDKKey.RUBY_ON_RAILS,
        tags: [SDKTag.SERVER],
        image: railsImage,
        docsLink: 'https://posthog.com/docs/libraries/rails',
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
        docsLink: 'https://posthog.com/docs/ai-observability/integrations/traceloop-posthog',
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
