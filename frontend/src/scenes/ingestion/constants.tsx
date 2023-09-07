import { PlatformType } from 'scenes/ingestion/types'
import { Segment, RSS } from './panels/ThirdPartyIcons'

export const TECHNICAL = 'TECHNICAL'
export const PLATFORM_TYPE = 'PLATFORM_TYPE'
export const FRAMEWORK = 'FRAMEWORK'
export const INSTRUCTIONS = 'INSTRUCTIONS'
export const VERIFICATION = 'VERIFICATION'

export const WEB = 'web'
export const MOBILE = 'mobile'
export const BACKEND = 'backend'
export const THIRD_PARTY = 'third-party'
export const platforms: PlatformType[] = [WEB, MOBILE, BACKEND]

export const NODEJS = 'NODEJS'
export const GO = 'GO'
export const RUBY = 'RUBY'
export const PYTHON = 'PYTHON'
export const PHP = 'PHP'
export const ELIXIR = 'ELIXIR'
export const API = 'API'

export const ANDROID = 'ANDROID'
export const IOS = 'IOS'
export const REACT_NATIVE = 'REACT_NATIVE'
export const FLUTTER = 'FLUTTER'

export const httpFrameworks = {
    [API]: 'HTTP API',
}
export const webFrameworks = {
    [NODEJS]: 'Node.js',
    [GO]: 'Go',
    [RUBY]: 'Ruby',
    [PYTHON]: 'Python',
    [PHP]: 'PHP',
    [ELIXIR]: 'Elixir',
}

export const mobileFrameworks = {
    [ANDROID]: 'Android',
    [IOS]: 'iOS',
    [REACT_NATIVE]: 'React Native',
    [FLUTTER]: 'Flutter',
}

export const allFrameworks = {
    ...webFrameworks,
    ...mobileFrameworks,
    ...httpFrameworks,
}
export interface ThirdPartySource {
    name: string
    icon: JSX.Element
    docsLink: string
    aboutLink: string
    labels?: string[]
    description?: string
}

export const thirdPartySources: ThirdPartySource[] = [
    {
        name: 'Segment',
        icon: <Segment />,
        docsLink: 'https://posthog.com/docs/integrate/third-party/segment',
        aboutLink: 'https://segment.com',
    },
    {
        name: 'Rudderstack',
        icon: (
            <img
                style={{ height: 36, width: 36 }}
                src={'https://raw.githubusercontent.com/rudderlabs/rudderstack-posthog-plugin/main/logo.png'}
            />
        ),
        docsLink: 'https://posthog.com/docs/integrate/third-party/rudderstack',
        aboutLink: 'https://rudderstack.com',
    },
    {
        name: 'RSS items',
        description: 'Send events from releases, blog posts, status pages, or any other RSS feed into PostHog',
        icon: <RSS />,
        docsLink: 'https://posthog.com/tutorials/rss-item-capture',
        aboutLink: 'https://en.wikipedia.org/wiki/RSS',
    },
]
