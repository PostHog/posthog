import { Logomark } from 'lib/brand/Logomark'

import { SDK, SDKKey, SDKTag } from '~/types'

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
import nextjsImage from './logos/nextjs.svg'
import nodejsImage from './logos/nodejs.svg'
import nuxtImage from './logos/nuxt.svg'
import openrouterImage from './logos/openrouter.png'
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
        name: 'OpenAI',
        key: SDKKey.OPENAI,
        tags: [],
        image: (
            <span className="flex w-8">
                <svg width="32" height="32" viewBox="0 0 721 721" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <title>OpenAI logo</title>
                    <path
                        d="M304.246 294.611V249.028C304.246 245.189 305.687 242.309 309.044 240.392L400.692 187.612C413.167 180.415 428.042 177.058 443.394 177.058C500.971 177.058 537.44 221.682 537.44 269.182C537.44 272.54 537.44 276.379 536.959 280.218L441.954 224.558C436.197 221.201 430.437 221.201 424.68 224.558L304.246 294.611ZM518.245 472.145V363.224C518.245 356.505 515.364 351.707 509.608 348.349L389.174 278.296L428.519 255.743C431.877 253.826 434.757 253.826 438.115 255.743L529.762 308.523C556.154 323.879 573.905 356.505 573.905 388.171C573.905 424.636 552.315 458.225 518.245 472.141V472.145ZM275.937 376.182L236.592 353.152C233.235 351.235 231.794 348.354 231.794 344.515V238.956C231.794 187.617 271.139 148.749 324.4 148.749C344.555 148.749 363.264 155.468 379.102 167.463L284.578 222.164C278.822 225.521 275.942 230.319 275.942 237.039V376.186L275.937 376.182ZM360.626 425.122L304.246 393.455V326.283L360.626 294.616L417.002 326.283V393.455L360.626 425.122ZM396.852 570.989C376.698 570.989 357.989 564.27 342.151 552.276L436.674 497.574C442.431 494.217 445.311 489.419 445.311 482.699V343.552L485.138 366.582C488.495 368.499 489.936 371.379 489.936 375.219V480.778C489.936 532.117 450.109 570.985 396.852 570.985V570.989ZM283.134 463.99L191.486 411.211C165.094 395.854 147.343 363.229 147.343 331.562C147.343 294.616 169.415 261.509 203.48 247.593V356.991C203.48 363.71 206.361 368.508 212.117 371.866L332.074 441.437L292.729 463.99C289.372 465.907 286.491 465.907 283.134 463.99ZM277.859 542.68C223.639 542.68 183.813 501.895 183.813 451.514C183.813 447.675 184.294 443.836 184.771 439.997L279.295 494.698C285.051 498.056 290.812 498.056 296.568 494.698L417.002 425.127V470.71C417.002 474.549 415.562 477.429 412.204 479.346L320.557 532.126C308.081 539.323 293.206 542.68 277.854 542.68H277.859ZM396.852 599.776C454.911 599.776 503.37 558.513 514.41 503.812C568.149 489.896 602.696 439.515 602.696 388.176C602.696 354.587 588.303 321.962 562.392 298.45C564.791 288.373 566.231 278.296 566.231 268.224C566.231 199.611 510.571 148.267 446.274 148.267C433.322 148.267 420.846 150.184 408.37 154.505C386.775 133.392 357.026 119.958 324.4 119.958C266.342 119.958 217.883 161.22 206.843 215.921C153.104 229.837 118.557 280.218 118.557 331.557C118.557 365.146 132.95 397.771 158.861 421.283C156.462 431.36 155.022 441.437 155.022 451.51C155.022 520.123 210.682 571.466 274.978 571.466C287.931 571.466 300.407 569.549 312.883 565.228C334.473 586.341 364.222 599.776 396.852 599.776Z"
                        fill="black"
                        className="dark:fill-white"
                    />
                </svg>
            </span>
        ),
        docsLink: 'https://posthog.com/docs/llm-analytics/installation/openai',
    },
    {
        name: 'Anthropic',
        key: SDKKey.ANTHROPIC,
        tags: [],
        image: (
            <span className="flex w-8">
                <svg width="32" height="23" viewBox="0 0 92.2 65" xmlns="http://www.w3.org/2000/svg">
                    <title>Anthropic logo</title>
                    <path
                        d="M66.5,0H52.4l25.7,65h14.1L66.5,0z M25.7,0L0,65h14.4l5.3-13.6h26.9L51.8,65h14.4L40.5,0C40.5,0,25.7,0,25.7,0z M24.3,39.3l8.8-22.8l8.8,22.8H24.3z"
                        fill="black"
                        className="dark:fill-white"
                    />
                </svg>
            </span>
        ),
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
        image: (
            <span className="flex w-8">
                <svg width="32" height="28" viewBox="0 0 57.7 50" xmlns="http://www.w3.org/2000/svg">
                    <title>Vercel logo</title>
                    <path d="M28.9,0l28.9,50H0L28.9,0z" fill="black" className="dark:fill-white" />
                </svg>
            </span>
        ),
        docsLink: 'https://posthog.com/docs/llm-analytics/installation/vercel-ai',
    },
    {
        name: 'LangChain',
        key: SDKKey.LANGCHAIN,
        tags: [],
        image: (
            <span className="flex w-8">
                <svg width="32" height="32" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                    <title>LangChain logo</title>
                    <path
                        d="M8.373 14.502c.013-.06.024-.118.038-.17l.061.145c.115.28.229.557.506.714-.012.254-.334.357-.552.326-.048-.114-.115-.228-.255-.164-.143.056-.3-.01-.266-.185.333-.012.407-.371.468-.666zM18.385 9.245c-.318 0-.616.122-.839.342l-.902.887c-.243.24-.368.572-.343.913l.006.056c.032.262.149.498.337.682.13.128.273.21.447.266a.866.866 0 01-.247.777l-.056.055a2.022 2.022 0 01-1.355-1.555l-.01-.057-.046.037c-.03.024-.06.05-.088.078l-.902.887a1.156 1.156 0 000 1.65c.231.228.535.342.84.342.304 0 .607-.114.838-.341l.902-.888a1.156 1.156 0 00-.436-1.921.953.953 0 01.276-.842 2.062 2.062 0 011.371 1.57l.01.057.047-.037c.03-.024.06-.05.088-.078l.902-.888a1.155 1.155 0 000-1.65 1.188 1.188 0 00-.84-.342z"
                        fill="#1C3C3C"
                        className="dark:fill-white"
                    />
                    <path
                        clipRule="evenodd"
                        d="M17.901 6H6.1C2.736 6 0 8.692 0 12s2.736 6 6.099 6H17.9C21.264 18 24 15.308 24 12s-2.736-6-6.099-6zm-5.821 9.407c-.195.04-.414.047-.562-.106-.045.1-.136.077-.221.056a.797.797 0 00-.061-.014c-.01.025-.017.048-.026.073-.329.021-.575-.309-.732-.558a4.991 4.991 0 00-.473-.21c-.172-.07-.345-.14-.509-.23a2.218 2.218 0 00-.004.173c-.002.244-.004.503-.227.651-.007.295.236.292.476.29.207-.003.41-.005.447.184a.485.485 0 01-.05.003c-.046 0-.092 0-.127.034-.117.111-.242.063-.372.013-.12-.046-.243-.094-.367-.02a2.318 2.318 0 00-.262.154.97.97 0 01-.548.194c-.024-.036-.014-.059.006-.08a.562.562 0 00.043-.056c.019-.028.035-.057.051-.084.054-.095.103-.18.242-.22-.185-.029-.344.055-.5.137l-.004.002a4.21 4.21 0 01-.065.034c-.097.04-.154.009-.212-.023-.082-.045-.168-.092-.376.04-.04-.032-.02-.061.002-.086.091-.109.21-.125.345-.119-.351-.193-.604-.056-.81.055-.182.098-.327.176-.471-.012-.065.017-.102.063-.138.108-.015.02-.03.038-.047.055-.035-.039-.027-.083-.018-.128l.005-.026a.242.242 0 00.003-.03l-.027-.01c-.053-.022-.105-.044-.09-.124-.117-.04-.2.03-.286.094-.054-.041-.01-.095.032-.145a.279.279 0 00.045-.065c.038-.065.103-.067.166-.069.054-.001.108-.003.145-.042.133-.075.297-.036.462.003.121.028.242.057.354.042.203.025.454-.18.352-.385-.186-.233-.184-.528-.183-.813v-.143c-.016-.108-.172-.233-.328-.358-.12-.095-.24-.191-.298-.28-.16-.177-.285-.382-.409-.585l-.015-.024c-.212-.404-.297-.86-.382-1.315-.103-.546-.205-1.09-.526-1.54-.266.144-.612.075-.841-.118-.12.107-.13.247-.138.396l-.001.014c-.297-.292-.26-.844-.023-1.17.097-.128.213-.233.342-.326.03-.021.04-.042.039-.074.235-1.04 1.836-.839 2.342-.103.167.206.281.442.395.678.137.283.273.566.5.795.22.237.452.463.684.689.359.35.718.699 1.032 1.089.49.587.839 1.276 1.144 1.97.05.092.08.193.11.293.044.15.089.299.2.417.026.035.084.088.149.148.156.143.357.328.289.409.009.019.027.04.05.06.032.028.074.058.116.088.122.087.25.178.16.25zm7.778-3.545l-.902.887c-.24.237-.537.413-.859.51l-.017.005-.006.015A2.021 2.021 0 0117.6 14l-.902.888c-.393.387-.916.6-1.474.6-.557 0-1.08-.213-1.474-.6a2.03 2.03 0 010-2.9l.902-.888c.242-.238.531-.409.859-.508l.016-.004.006-.016c.105-.272.265-.516.475-.724l.902-.887c.393-.387.917-.6 1.474-.6.558 0 1.08.213 1.474.6.394.387.61.902.61 1.45 0 .549-.216 1.064-.61 1.45v.001z"
                        fill="#1C3C3C"
                        fillRule="evenodd"
                        className="dark:fill-white"
                    />
                </svg>
            </span>
        ),
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
