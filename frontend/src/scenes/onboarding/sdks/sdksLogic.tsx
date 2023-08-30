import { kea } from 'kea'

import type { sdksLogicType } from './sdksLogicType'
import { SDK } from '~/types'

export const allSDKs: SDK[] = [
    // Web
    {
        name: 'JavaScript web',
        key: 'javascript_web',
        recommended: true,
        tags: ['web'],
        image: require('./logos/javascript_web.svg'),
    },
    {
        name: 'React',
        key: 'react',
        tags: ['web'],
        image: require('./logos/react.svg'),
    },
    {
        name: 'Next.js',
        key: 'nextjs',
        tags: ['web'],
        image: require('./logos/nextjs.svg'),
    },
    {
        name: 'Gatsby',
        key: 'gatsby',
        tags: ['web'],
        image: require('./logos/gatsby.svg'),
    },
    // ...other web frameworks
    // Mobile
    {
        name: 'iOS',
        key: 'ios',
        tags: ['mobile'],
        image: require('./logos/ios.svg'),
    },
    {
        name: 'Android',
        key: 'android',
        tags: ['mobile'],
        image: require('./logos/android.svg'),
    },
    {
        name: 'React Native',
        key: 'react',
        tags: ['mobile'],
        image: require('./logos/react.svg'),
    },
    {
        name: 'Flutter',
        key: 'flutter',
        tags: ['mobile'],
        image: require('./logos/flutter.svg'),
    },
    // ...other mobile frameworks
    // Server
    {
        name: 'Node.js',
        key: 'nodejs',
        tags: ['server'],
        image: require('./logos/nodejs.svg'),
    },
    {
        name: 'Python',
        key: 'python',
        tags: ['server'],
        image: require('./logos/python.svg'),
    },
    {
        name: 'Ruby',
        key: 'ruby',
        tags: ['server'],
        image: require('./logos/ruby.svg'),
    },
]

export const sdksLogic = kea<sdksLogicType>({
    path: ['scenes', 'onboarding', 'sdks', 'sdksLogic'],

    actions: {
        setSourceFilter: (sourceFilter: string | null) => ({ sourceFilter }),
        setSDKs: (sdks: SDK[]) => ({ sdks }),
    },

    reducers: {
        sourceFilter: [
            null as string | null,
            {
                setSourceFilter: (_, { sourceFilter }) => sourceFilter,
            },
        ],
        sdks: [
            allSDKs,
            {
                setSDKs: (_, { sdks }) => sdks,
                setSourceFilter: (_, { sourceFilter }) => {
                    if (!sourceFilter) {
                        return allSDKs
                    }
                    return allSDKs.filter((sdk) => sdk.tags.includes(sourceFilter))
                },
            },
        ],
    },
})
