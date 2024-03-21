import { Logomark } from '~/toolbar/assets/Logomark'
import { SDK, SDKKey, SDKTag } from '~/types'

export const allSDKs: SDK[] = [
    // Web
    {
        name: 'JavaScript web',
        key: SDKKey.JS_WEB,
        recommended: true,
        tags: [SDKTag.RECOMMENDED, SDKTag.WEB],
        image: require('./logos/javascript_web.svg'),
        docsLink: 'https://posthog.com/docs/libraries/js',
    },
    {
        name: 'HTML snippet',
        key: SDKKey.HTML_SNIPPET,
        recommended: true,
        tags: [SDKTag.RECOMMENDED, SDKTag.WEB],
        image: require('./logos/html.svg'),
        docsLink: 'https://posthog.com/docs/libraries/js',
    },
    {
        name: 'Android',
        key: SDKKey.ANDROID,
        tags: [SDKTag.MOBILE],
        image: require('./logos/android.svg'),
        docsLink: 'https://posthog.com/docs/libraries/android',
    },
    {
        name: 'Angular',
        key: SDKKey.ANGULAR,
        tags: [SDKTag.WEB],
        image: require('./logos/angular.svg'),
        docsLink: 'https://posthog.com/docs/libraries/angular',
    },
    {
        name: 'API',
        key: SDKKey.API,
        tags: [SDKTag.SERVER],
        image: (
            <span className="flex w-4">
                <Logomark />
            </span>
        ),
        docsLink: 'https://posthog.com/docs/api',
    },
    {
        name: 'Astro',
        key: SDKKey.ASTRO,
        tags: [SDKTag.WEB],
        image: require('./logos/astro.svg'),
        docsLink: 'https://posthog.com/docs/libraries/astro',
    },
    {
        name: 'Bubble',
        key: SDKKey.BUBBLE,
        tags: [SDKTag.WEB],
        image: require('./logos/bubble.svg'),
        docsLink: 'https://posthog.com/docs/libraries/bubble',
    },
    {
        name: 'Elixir',
        key: SDKKey.ELIXIR,
        tags: [SDKTag.SERVER],
        image: require('./logos/elixir.svg'),
        docsLink: 'https://posthog.com/docs/libraries/elixir',
    },
    {
        name: 'Flutter',
        key: SDKKey.FLUTTER,
        tags: [SDKTag.MOBILE],
        image: require('./logos/flutter.svg'),
        docsLink: 'https://posthog.com/docs/libraries/flutter',
    },
    {
        name: 'Framer',
        key: SDKKey.FRAMER,
        tags: [SDKTag.WEB],
        image: require('./logos/framer.svg'),
        docsLink: 'https://posthog.com/docs/libraries/framer',
    },
    {
        name: 'Gatsby',
        key: SDKKey.GATSBY,
        tags: [SDKTag.WEB],
        image: require('./logos/gatsby.svg'),
        docsLink: 'https://posthog.com/docs/libraries/gatsby',
    },
    {
        name: 'Go',
        key: SDKKey.GO,
        tags: [SDKTag.SERVER],
        image: require('./logos/go.svg'),
        docsLink: 'https://posthog.com/docs/libraries/go',
    },
    {
        name: 'iOS',
        key: SDKKey.IOS,
        tags: [SDKTag.MOBILE],
        image: require('./logos/ios.svg'),
        docsLink: 'https://posthog.com/docs/libraries/ios',
    },
    {
        name: 'Java',
        key: SDKKey.JAVA,
        tags: [SDKTag.SERVER],
        image: require('./logos/java.svg'),
        docsLink: 'https://posthog.com/docs/libraries/java',
    },
    {
        name: 'Next.js',
        key: SDKKey.NEXT_JS,
        tags: [SDKTag.WEB],
        image: require('./logos/nextjs.svg'),
        docsLink: 'https://posthog.com/docs/libraries/next-js',
    },
    {
        name: 'Node.js',
        key: SDKKey.NODE_JS,
        tags: [SDKTag.SERVER, SDKTag.RECOMMENDED],
        recommended: true,
        image: require('./logos/nodejs.svg'),
        docsLink: 'https://posthog.com/docs/libraries/node',
    },
    {
        name: 'Nuxt.js',
        key: SDKKey.NUXT_JS,
        tags: [SDKTag.WEB],
        image: require('./logos/nuxt.svg'),
        docsLink: 'https://posthog.com/docs/libraries/nuxt-js',
    },
    {
        name: 'PHP',
        key: SDKKey.PHP,
        tags: [SDKTag.SERVER],
        image: require('./logos/php.svg'),
        docsLink: 'https://posthog.com/docs/libraries/php',
    },
    {
        name: 'Python',
        key: SDKKey.PYTHON,
        tags: [SDKTag.SERVER, SDKTag.RECOMMENDED],
        recommended: true,
        image: require('./logos/python.svg'),
        docsLink: 'https://posthog.com/docs/libraries/python',
    },
    {
        name: 'React',
        key: SDKKey.REACT,
        tags: [SDKTag.WEB, SDKTag.RECOMMENDED],
        recommended: true,
        image: require('./logos/react.svg'),
        docsLink: 'https://posthog.com/docs/libraries/react',
    },
    {
        name: 'React Native',
        key: SDKKey.REACT_NATIVE,
        tags: [SDKTag.MOBILE],
        image: require('./logos/react.svg'),
        docsLink: 'https://posthog.com/docs/libraries/react-native',
    },
    {
        name: 'Ruby',
        key: SDKKey.RUBY,
        tags: [SDKTag.SERVER],
        image: require('./logos/ruby.svg'),
        docsLink: 'https://posthog.com/docs/libraries/ruby',
    },
    {
        name: 'Vue.js',
        key: SDKKey.VUE_JS,
        tags: [SDKTag.WEB],
        image: require('./logos/vue.svg'),
        docsLink: 'https://posthog.com/docs/libraries/vue-js',
    },
    {
        name: 'Rust',
        key: SDKKey.RUST,
        tags: [SDKTag.SERVER],
        image: require('./logos/rust.svg'),
        docsLink: 'https://posthog.com/docs/libraries/rust',
    },
    // integrations
    {
        name: 'Google Tag Manager',
        key: SDKKey.GOOGLE_TAG_MANAGER,
        tags: [SDKTag.WEB, SDKTag.INTEGRATION],
        image: require('./logos/gtm.svg'),
        docsLink: 'https://posthog.com/docs/libraries/google-tag-manager',
    },
    {
        name: 'Segment',
        key: SDKKey.SEGMENT,
        tags: [SDKTag.INTEGRATION],
        image: require('./logos/segment.svg'),
        docsLink: 'https://posthog.com/docs/libraries/segment',
    },
    {
        name: 'RudderStack',
        key: SDKKey.RUDDERSTACK,
        tags: [SDKTag.INTEGRATION],
        image: require('./logos/rudderstack.svg'),
        docsLink: 'https://posthog.com/docs/libraries/rudderstack',
    },
    {
        name: 'Docusaurus',
        key: SDKKey.DOCUSAURUS,
        tags: [SDKTag.INTEGRATION],
        image: require('./logos/docusaurus.svg'),
        docsLink: 'https://posthog.com/docs/libraries/docusaurus',
    },
    {
        name: 'Shopify',
        key: SDKKey.SHOPIFY,
        tags: [SDKTag.INTEGRATION],
        image: require('./logos/shopify.svg'),
        docsLink: 'https://posthog.com/docs/libraries/shopify',
    },
    {
        name: 'Wordpress',
        key: SDKKey.WORDPRESS,
        tags: [SDKTag.INTEGRATION],
        image: require('./logos/wordpress.svg'),
        docsLink: 'https://posthog.com/docs/libraries/wordpress',
    },
    {
        name: 'Sentry',
        key: SDKKey.SENTRY,
        tags: [SDKTag.INTEGRATION],
        image: require('./logos/sentry.svg'),
        docsLink: 'https://posthog.com/docs/libraries/sentry',
    },
    {
        name: 'Retool',
        key: SDKKey.RETOOL,
        tags: [SDKTag.INTEGRATION],
        image: require('./logos/retool.svg'),
        docsLink: 'https://posthog.com/docs/libraries/retool',
    },
]
