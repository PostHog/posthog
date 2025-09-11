import { Logomark } from '~/toolbar/assets/Logomark'
import { SDK, SDKKey, SDKTag } from '~/types'

import androidImage from './logos/android.svg'
import angularImage from './logos/angular.svg'
import djangoImage from './logos/django.svg'
import docusaurusImage from './logos/docusaurus.svg'
import elixirImage from './logos/elixir.svg'
import flutterImage from './logos/flutter.svg'
import gatsbyImage from './logos/gatsby.svg'
import goImage from './logos/go.svg'
import gtmImage from './logos/gtm.svg'
import heliconeImage from './logos/helicone.svg'
import htmlImage from './logos/html.svg'
import javaImage from './logos/java.svg'
import jsImage from './logos/javascript_web.svg'
import langfuseImage from './logos/langfuse.svg'
import laravelImage from './logos/laravel.svg'
import nextjsImage from './logos/nextjs.svg'
import nodejsImage from './logos/nodejs.svg'
import nuxtImage from './logos/nuxt.svg'
import phpImage from './logos/php.svg'
import pythonImage from './logos/python.svg'
import reactImage from './logos/react.svg'
import reactNativeImage from './logos/react.svg'
import retoolImage from './logos/retool.svg'
import rubyImage from './logos/ruby.svg'
import rudderstackImage from './logos/rudderstack.svg'
import rustImage from './logos/rust.svg'
import segmentImage from './logos/segment.svg'
import sentryImage from './logos/sentry.svg'
import shopifyImage from './logos/shopify.svg'
import svelteImage from './logos/svelte.svg'
import traceloopImage from './logos/traceloop.svg'
import vueImage from './logos/vue.svg'
import webflowImage from './logos/webflow.svg'
import wordpressImage from './logos/wordpress.svg'

export const allSDKs: SDK[] = [
    // Web
    {
        name: 'Next.js',
        key: SDKKey.NEXT_JS,
        tags: [SDKTag.WEB, SDKTag.RECOMMENDED],
        recommended: true,
        image: nextjsImage,
        docsLink: 'https://posthog.com/docs/libraries/next-js',
    },
    {
        name: 'HTML snippet',
        key: SDKKey.HTML_SNIPPET,
        recommended: true,
        tags: [SDKTag.RECOMMENDED, SDKTag.WEB],
        image: htmlImage,
        docsLink: 'https://posthog.com/docs/libraries/js',
    },
    {
        name: 'JavaScript web',
        key: SDKKey.JS_WEB,
        recommended: true,
        tags: [SDKTag.RECOMMENDED, SDKTag.WEB],
        image: jsImage,
        docsLink: 'https://posthog.com/docs/libraries/js',
    },
    {
        name: 'React',
        key: SDKKey.REACT,
        tags: [SDKTag.WEB, SDKTag.RECOMMENDED],
        recommended: true,
        image: reactImage,
        docsLink: 'https://posthog.com/docs/libraries/react',
    },
    {
        name: 'React Native',
        key: SDKKey.REACT_NATIVE,
        tags: [SDKTag.MOBILE, SDKTag.RECOMMENDED],
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
        image: (
            <span className="flex w-4">
                <svg width="24" height="24" viewBox="0 0 85 107" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <title>Astro logo</title>
                    <path
                        d="M27.5894 91.1365C22.7555 86.7178 21.3444 77.4335 23.3583 70.7072C26.8503 74.948 31.6888 76.2914 36.7005 77.0497C44.4375 78.2199 52.0359 77.7822 59.2232 74.2459C60.0454 73.841 60.8052 73.3027 61.7036 72.7574C62.378 74.714 62.5535 76.6892 62.318 78.6996C61.7452 83.5957 59.3086 87.3778 55.4332 90.2448C53.8835 91.3916 52.2437 92.4167 50.6432 93.4979C45.7262 96.8213 44.3959 100.718 46.2435 106.386C46.2874 106.525 46.3267 106.663 46.426 107C43.9155 105.876 42.0817 104.24 40.6845 102.089C39.2087 99.8193 38.5066 97.3081 38.4696 94.5909C38.4511 93.2686 38.4511 91.9345 38.2733 90.6309C37.8391 87.4527 36.3471 86.0297 33.5364 85.9478C30.6518 85.8636 28.37 87.6469 27.7649 90.4554C27.7187 90.6707 27.6517 90.8837 27.5847 91.1341L27.5894 91.1365Z"
                        fill="black"
                        className="dark:fill-white"
                    />
                    <path
                        d="M27.5894 91.1365C22.7555 86.7178 21.3444 77.4335 23.3583 70.7072C26.8503 74.948 31.6888 76.2914 36.7005 77.0497C44.4375 78.2199 52.0359 77.7822 59.2232 74.2459C60.0454 73.841 60.8052 73.3027 61.7036 72.7574C62.378 74.714 62.5535 76.6892 62.318 78.6996C61.7452 83.5957 59.3086 87.3778 55.4332 90.2448C53.8835 91.3916 52.2437 92.4167 50.6432 93.4979C45.7262 96.8213 44.3959 100.718 46.2435 106.386C46.2874 106.525 46.3267 106.663 46.426 107C43.9155 105.876 42.0817 104.24 40.6845 102.089C39.2087 99.8193 38.5066 97.3081 38.4696 94.5909C38.4511 93.2686 38.4511 91.9345 38.2733 90.6309C37.8391 87.4527 36.3471 86.0297 33.5364 85.9478C30.6518 85.8636 28.37 87.6469 27.7649 90.4554C27.7187 90.6707 27.6517 90.8837 27.5847 91.1341L27.5894 91.1365Z"
                        fill="url(#astro_logo_gradient)"
                    />
                    <path
                        d="M0 69.5866C0 69.5866 14.3139 62.6137 28.6678 62.6137L39.4901 29.1204C39.8953 27.5007 41.0783 26.3999 42.4139 26.3999C43.7495 26.3999 44.9325 27.5007 45.3377 29.1204L56.1601 62.6137C73.1601 62.6137 84.8278 69.5866 84.8278 69.5866C84.8278 69.5866 60.5145 3.35233 60.467 3.21944C59.7692 1.2612 58.5911 0 57.0029 0H27.8274C26.2392 0 25.1087 1.2612 24.3634 3.21944C24.3108 3.34983 0 69.5866 0 69.5866Z"
                        fill="black"
                        className="dark:fill-white"
                    />
                    <defs>
                        <linearGradient
                            id="astro_logo_gradient"
                            x1="22.4702"
                            y1="107"
                            x2="69.1451"
                            y2="84.9468"
                            gradientUnits="userSpaceOnUse"
                        >
                            <stop stopColor="#D83333" />
                            <stop offset="1" stopColor="#F041FF" />
                        </linearGradient>
                    </defs>
                </svg>
            </span>
        ),
        docsLink: 'https://posthog.com/docs/libraries/astro',
    },
    {
        name: 'Bubble',
        key: SDKKey.BUBBLE,
        tags: [SDKTag.WEB],
        image: (
            <span className="flex w-4">
                <svg
                    className="w-4 h-4"
                    width="16"
                    height="18"
                    viewBox="0 0 256 276"
                    version="1.1"
                    xmlns="http://www.w3.org/2000/svg"
                    preserveAspectRatio="xMidYMid"
                >
                    <title>Bubble logo</title>
                    <g>
                        <path
                            className="dark:fill-white"
                            d="M156.687886,71.5306475 C131.928045,71.5306475 107.524298,82.1604077 88.8931172,103.059013 L88.8931172,0 L52.0240423,0 L52.0240423,173.506229 C52.0240423,173.510361 52.0240423,173.514494 52.0240423,173.519315 C52.0240423,229.845404 97.6852437,275.506605 154.012021,275.506605 C210.33811,275.506605 256,229.845404 256,173.519315 C256,117.193226 213.013974,71.5306475 156.687886,71.5306475 M154.012021,236.224775 C119.380066,236.224775 91.3051835,208.149893 91.3051835,173.518626 C91.3051835,138.886671 119.380066,110.811789 154.012021,110.811789 C188.643288,110.811789 216.71817,138.886671 216.71817,173.518626 C216.71817,208.150582 188.643288,236.224775 154.012021,236.224775"
                            fill="#262626"
                        />
                        <path
                            d="M25.2199377,225.066041 C11.2909777,225.066041 1.0658141e-14,236.357707 1.0658141e-14,250.285979 C1.0658141e-14,264.21425 11.2909777,275.505916 25.2199377,275.505916 C39.1488977,275.505916 50.4398754,264.21425 50.4398754,250.285979 C50.4398754,236.357707 39.1488977,225.066041 25.2199377,225.066041"
                            fill="#0000FF"
                        />
                    </g>
                </svg>
            </span>
        ),
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
        image: (
            <span className="flex w-4">
                <svg
                    fill="#000000"
                    className="w-4 h-4 dark:fill-white"
                    viewBox="0 0 24 24"
                    role="img"
                    xmlns="http://www.w3.org/2000/svg"
                >
                    <title>Framer logo</title>
                    <path d="M4 0h16v8h-8zM4 8h8l8 8H4zM4 16h8v8z" />
                </svg>
            </span>
        ),
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
        name: 'iOS',
        key: SDKKey.IOS,
        tags: [SDKTag.MOBILE],
        image: (
            <span className="flex w-4">
                <svg width="21" height="24" fill="none" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 21 24">
                    <title>iOS logo</title>
                    <path
                        d="M16.844 23.016c-1.3 1.262-2.736 1.066-4.104.47-1.454-.607-2.784-.645-4.32 0-1.913.826-2.928.586-4.08-.47C-2.164 16.32-1.204 6.12 6.188 5.736c1.793.096 3.048.991 4.104 1.066 1.57-.32 3.072-1.234 4.752-1.114 2.018.163 3.528.96 4.536 2.393-4.152 2.496-3.168 7.968.646 9.504-.764 2.004-1.743 3.984-3.384 5.448l.002-.017zM10.148 5.664C9.954 2.688 12.366.24 15.14 0c.382 3.432-3.12 6-4.992 5.664z"
                        fill="#000"
                        className="dark:fill-white"
                    />
                </svg>
            </span>
        ),
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
        tags: [SDKTag.SERVER, SDKTag.RECOMMENDED],
        recommended: true,
        image: nodejsImage,
        docsLink: 'https://posthog.com/docs/libraries/node',
    },
    {
        name: 'Nuxt.js',
        key: SDKKey.NUXT_JS,
        tags: [SDKTag.WEB],
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
        tags: [SDKTag.SERVER, SDKTag.RECOMMENDED],
        recommended: true,
        image: pythonImage,
        docsLink: 'https://posthog.com/docs/libraries/python',
    },
    {
        name: 'Remix',
        key: SDKKey.REMIX,
        tags: [SDKTag.WEB],
        image: (
            <span className="flex w-4 pl-1">
                <svg width="21" height="24" viewBox="0 0 411 473" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <title>Remix logo</title>
                    <path
                        fillRule="evenodd"
                        clipRule="evenodd"
                        d="M392.946 364.768C397.201 419.418 397.201 445.036 397.201 473H270.756C270.756 466.909 270.865 461.337 270.975 455.687C271.317 438.123 271.674 419.807 268.828 382.819C265.067 328.667 241.748 316.634 198.871 316.634H160.883H0V218.109H204.889C259.049 218.109 286.13 201.633 286.13 158.011C286.13 119.654 259.049 96.4098 204.889 96.4098H0V0H227.456C350.069 0 411 57.9117 411 150.42C411 219.613 368.123 264.739 310.201 272.26C359.096 282.037 387.681 309.865 392.946 364.768Z"
                        fill="#121212"
                        className="dark:fill-white"
                    />
                    <path
                        d="M0 473V399.553H133.697C156.029 399.553 160.878 416.116 160.878 425.994V473H0Z"
                        fill="#121212"
                        className="dark:fill-white"
                    />
                </svg>
            </span>
        ),
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
        name: 'Traceloop',
        key: SDKKey.TRACELOOP,
        tags: [SDKTag.LLM],
        image: traceloopImage,
        docsLink: 'https://posthog.com/docs/llm-analytics/integrations/traceloop-posthog',
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
    // integrations
    {
        name: 'Google Tag Manager',
        key: SDKKey.GOOGLE_TAG_MANAGER,
        tags: [SDKTag.WEB, SDKTag.INTEGRATION],
        image: gtmImage,
        docsLink: 'https://posthog.com/docs/libraries/google-tag-manager',
    },
    {
        name: 'Segment',
        key: SDKKey.SEGMENT,
        tags: [SDKTag.INTEGRATION],
        image: segmentImage,
        docsLink: 'https://posthog.com/docs/libraries/segment',
    },
    {
        name: 'RudderStack',
        key: SDKKey.RUDDERSTACK,
        tags: [SDKTag.INTEGRATION],
        image: rudderstackImage,
        docsLink: 'https://posthog.com/docs/libraries/rudderstack',
    },
    {
        name: 'Docusaurus',
        key: SDKKey.DOCUSAURUS,
        tags: [SDKTag.INTEGRATION],
        image: docusaurusImage,
        docsLink: 'https://posthog.com/docs/libraries/docusaurus',
    },
    {
        name: 'Shopify',
        key: SDKKey.SHOPIFY,
        tags: [SDKTag.INTEGRATION],
        image: shopifyImage,
        docsLink: 'https://posthog.com/docs/libraries/shopify',
    },
    {
        name: 'Wordpress',
        key: SDKKey.WORDPRESS,
        tags: [SDKTag.INTEGRATION],
        image: wordpressImage,
        docsLink: 'https://posthog.com/docs/libraries/wordpress',
    },
    {
        name: 'Sentry',
        key: SDKKey.SENTRY,
        tags: [SDKTag.INTEGRATION],
        image: sentryImage,
        docsLink: 'https://posthog.com/docs/libraries/sentry',
    },
    {
        name: 'Retool',
        key: SDKKey.RETOOL,
        tags: [SDKTag.INTEGRATION],
        image: retoolImage,
        docsLink: 'https://posthog.com/docs/libraries/retool',
    },
]
