import { Logomark } from '~/toolbar/assets/Logomark'
import { SDK, SDKKey } from '~/types'

export const allSDKs: SDK[] = [
    // Web
    {
        name: 'JavaScript web',
        key: SDKKey.JS_WEB,
        recommended: true,
        tags: ['web'],
        image: require('./logos/javascript_web.svg'),
    },
    {
        name: 'React',
        key: SDKKey.REACT,
        tags: ['web'],
        image: require('./logos/react.svg'),
    },
    {
        name: 'Next.js',
        key: SDKKey.NEXT_JS,
        tags: ['web'],
        image: require('./logos/nextjs.svg'),
    },
    {
        name: 'Gatsby',
        key: SDKKey.GATSBY,
        tags: ['web'],
        image: require('./logos/gatsby.svg'),
    },
    // ...other web frameworks
    // Mobile
    {
        name: 'iOS',
        key: SDKKey.IOS,
        tags: ['mobile'],
        image: require('./logos/ios.svg'),
    },
    {
        name: 'Android',
        key: SDKKey.ANDROID,
        tags: ['mobile'],
        image: require('./logos/android.svg'),
    },
    {
        name: 'React Native',
        key: SDKKey.REACT_NATIVE,
        tags: ['mobile'],
        image: require('./logos/react.svg'),
    },
    {
        name: 'Flutter',
        key: SDKKey.FLUTTER,
        tags: ['mobile'],
        image: require('./logos/flutter.svg'),
    },
    // ...other mobile frameworks
    // Server
    {
        name: 'Node.js',
        key: SDKKey.NODE_JS,
        tags: ['server'],
        image: require('./logos/nodejs.svg'),
    },
    {
        name: 'Python',
        key: SDKKey.PYTHON,
        tags: ['server'],
        image: require('./logos/python.svg'),
    },
    {
        name: 'Ruby',
        key: SDKKey.RUBY,
        tags: ['server'],
        image: require('./logos/ruby.svg'),
    },
    {
        name: 'PHP',
        key: SDKKey.PHP,
        tags: ['server'],
        image: require('./logos/php.svg'),
    },
    {
        name: 'Go',
        key: SDKKey.GO,
        tags: ['server'],
        image: require('./logos/go.svg'),
    },
    {
        name: 'Elixir',
        key: SDKKey.ELIXIR,
        tags: ['server'],
        image: require('./logos/elixir.svg'),
    },
    {
        name: 'API',
        key: SDKKey.API,
        tags: ['server'],
        image: <Logomark />,
    },
]
