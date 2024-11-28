import { IconServer } from '@posthog/icons'
import {
    IconAndroidOS,
    IconAppleIOS,
    IconFlutter,
    IconGolang,
    IconJavascript,
    IconNodeJS,
    IconPHP,
    IconPython,
    IconReact,
    IconRuby,
} from 'lib/lemon-ui/icons'

import { SDKKey } from '~/types'

import {
    AndroidSnippet,
    APISnippet,
    FeatureFlagSnippet,
    FlutterSnippet,
    GolangSnippet,
    iOSSnippet,
    JSBootstrappingSnippet,
    JSSnippet,
    NodeJSSnippet,
    PHPSnippet,
    PythonSnippet,
    ReactNativeSnippet,
    ReactSnippet,
    RubySnippet,
    UTM_TAGS,
} from './FeatureFlagSnippets'

const DOC_BASE_URL = 'https://posthog.com/docs/'
export const FF_ANCHOR = '#feature-flags'
export const PAYLOADS_ANCHOR = '#feature-flag-payloads'
export const LOCAL_EVAL_ANCHOR = '#local-evaluation'
export const BOOTSTRAPPING_ANCHOR = '#bootstrapping-flags'

export interface InstructionOption {
    value: string
    documentationLink: string
    Snippet: ({ flagKey, multivariant, groupType }: FeatureFlagSnippet) => JSX.Element
    type: LibraryType
    key: SDKKey
    Icon: React.ElementType
}

export enum LibraryType {
    Client = 'Client',
    Server = 'Server',
}

export const OPTIONS: InstructionOption[] = [
    {
        value: 'JavaScript',
        documentationLink: `${DOC_BASE_URL}libraries/js${UTM_TAGS}`,
        Snippet: JSSnippet,
        type: LibraryType.Client,
        key: SDKKey.JS_WEB,
        Icon: IconJavascript,
    },
    {
        value: 'Android',
        documentationLink: `${DOC_BASE_URL}libraries/android${UTM_TAGS}`,
        Snippet: AndroidSnippet,
        type: LibraryType.Client,
        key: SDKKey.ANDROID,
        Icon: IconAndroidOS,
    },
    {
        value: 'API',
        documentationLink: `${DOC_BASE_URL}api/post-only-endpoints#example-request--response-decide-v3`,
        Snippet: APISnippet,
        type: LibraryType.Server,
        key: SDKKey.API,
        Icon: IconServer,
    },
    {
        value: 'Go',
        documentationLink: `${DOC_BASE_URL}libraries/go${UTM_TAGS}`,
        Snippet: GolangSnippet,
        type: LibraryType.Server,
        key: SDKKey.GO,
        Icon: IconGolang,
    },
    {
        value: 'Flutter',
        documentationLink: `${DOC_BASE_URL}libraries/flutter${UTM_TAGS}`,
        Snippet: FlutterSnippet,
        type: LibraryType.Client,
        key: SDKKey.FLUTTER,
        Icon: IconFlutter,
    },
    {
        value: 'iOS',
        documentationLink: `${DOC_BASE_URL}libraries/ios${UTM_TAGS}`,
        Snippet: iOSSnippet,
        type: LibraryType.Client,
        key: SDKKey.IOS,
        Icon: IconAppleIOS,
    },
    {
        value: 'Node.js',
        documentationLink: `${DOC_BASE_URL}libraries/node${UTM_TAGS}`,
        Snippet: NodeJSSnippet,
        type: LibraryType.Server,
        key: SDKKey.NODE_JS,
        Icon: IconNodeJS,
    },
    {
        value: 'React',
        documentationLink: `${DOC_BASE_URL}libraries/react${UTM_TAGS}`,
        Snippet: ReactSnippet,
        type: LibraryType.Client,
        key: SDKKey.REACT,
        Icon: IconReact,
    },
    {
        value: 'React Native',
        documentationLink: `${DOC_BASE_URL}libraries/react-native${UTM_TAGS}`,
        Snippet: ReactNativeSnippet,
        type: LibraryType.Client,
        key: SDKKey.REACT_NATIVE,
        Icon: IconReact,
    },
    {
        value: 'PHP',
        documentationLink: `${DOC_BASE_URL}libraries/php${UTM_TAGS}`,
        Snippet: PHPSnippet,
        type: LibraryType.Server,
        key: SDKKey.PHP,
        Icon: IconPHP,
    },
    {
        value: 'Python',
        documentationLink: `${DOC_BASE_URL}libraries/python${UTM_TAGS}`,
        Snippet: PythonSnippet,
        type: LibraryType.Server,
        key: SDKKey.PYTHON,
        Icon: IconPython,
    },
    {
        value: 'Ruby',
        documentationLink: `${DOC_BASE_URL}libraries/ruby${UTM_TAGS}`,
        Snippet: RubySnippet,
        type: LibraryType.Server,
        key: SDKKey.RUBY,
        Icon: IconRuby,
    },
]

export const LOCAL_EVALUATION_LIBRARIES: string[] = [SDKKey.NODE_JS, SDKKey.PYTHON, SDKKey.RUBY, SDKKey.PHP, SDKKey.GO]

export const PAYLOAD_LIBRARIES: string[] = [
    SDKKey.JS_WEB,
    SDKKey.NODE_JS,
    SDKKey.PYTHON,
    SDKKey.RUBY,
    SDKKey.REACT,
    SDKKey.ANDROID,
    SDKKey.REACT_NATIVE,
    SDKKey.IOS,
    SDKKey.FLUTTER,
]

export const BOOTSTRAPPING_OPTIONS: InstructionOption[] = [
    {
        value: 'JavaScript',
        documentationLink: `${DOC_BASE_URL}libraries/js${UTM_TAGS}${BOOTSTRAPPING_ANCHOR}`,
        Snippet: JSBootstrappingSnippet,
        type: LibraryType.Client,
        key: SDKKey.JS_WEB,
        Icon: IconJavascript,
    },
    {
        value: 'React Native',
        documentationLink: `${DOC_BASE_URL}libraries/react-native${UTM_TAGS}${BOOTSTRAPPING_ANCHOR}`,
        Snippet: JSBootstrappingSnippet,
        type: LibraryType.Client,
        key: SDKKey.REACT_NATIVE,
        Icon: IconReact,
    },
]
