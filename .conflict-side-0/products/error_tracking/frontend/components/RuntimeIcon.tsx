import {
    IconAndroid,
    IconApple,
    IconCSharp,
    IconDart,
    IconElixir,
    IconFlutter,
    IconGo,
    IconJava,
    IconJavascript,
    IconLogomark,
    IconNode,
    IconPHP,
    IconPython,
    IconReact,
    IconRuby,
    IconRust,
    IconSwift,
} from '@posthog/icons'
import { IconProps } from '@posthog/icons/dist/src/types/icon-types'

import { ErrorTrackingRuntime } from 'lib/components/Errors/types'

const RuntimeIconMap: Record<ErrorTrackingRuntime, React.FC> = {
    python: IconPython,
    web: IconJavascript,
    node: IconNode,
    ruby: IconRuby,
    go: IconGo,
    rust: IconRust,
    dotnet: IconCSharp,
    php: IconPHP,
    java: IconJava,
    android: IconAndroid,
    ios: IconApple,
    elixir: IconElixir,
    swift: IconSwift,
    dart: IconDart,
    flutter: IconFlutter,
    ['react-native']: IconReact,

    unknown: IconLogomark,
}

export function RuntimeIcon({ runtime, ...props }: { runtime: ErrorTrackingRuntime } & IconProps): JSX.Element {
    const Icon = RuntimeIconMap[runtime]
    return <Icon {...props} />
}
