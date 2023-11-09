import { SDKKey } from '~/types'
import {
    UTM_TAGS,
    FeatureFlagSnippet,
    JSSnippet,
    AndroidSnippet,
    iOSSnippet,
    ReactNativeSnippet,
    NodeJSSnippet,
    PythonSnippet,
    RubySnippet,
    APISnippet,
    PHPSnippet,
    GolangSnippet,
    JSBootstrappingSnippet,
    ReactSnippet,
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
}

export enum LibraryType {
    Client = 'Client',
    Server = 'Server',
}

export const OPTIONS: InstructionOption[] = [
    {
        value: 'JavaScript',
        documentationLink: `${DOC_BASE_URL}integrations/js-integration${UTM_TAGS}`,
        Snippet: JSSnippet,
        type: LibraryType.Client,
        key: SDKKey.JS_WEB,
    },
    {
        value: 'Android',
        documentationLink: `${DOC_BASE_URL}integrate/client/android${UTM_TAGS}`,
        Snippet: AndroidSnippet,
        type: LibraryType.Client,
        key: SDKKey.ANDROID,
    },
    {
        value: 'iOS',
        documentationLink: `${DOC_BASE_URL}integrate/client/ios${UTM_TAGS}`,
        Snippet: iOSSnippet,
        type: LibraryType.Client,
        key: SDKKey.IOS,
    },
    {
        value: 'React Native',
        documentationLink: `${DOC_BASE_URL}integrate/client/react-native${UTM_TAGS}`,
        Snippet: ReactNativeSnippet,
        type: LibraryType.Client,
        key: SDKKey.REACT_NATIVE,
    },
    {
        value: 'React',
        documentationLink: `${DOC_BASE_URL}libraries/react${UTM_TAGS}`,
        Snippet: ReactSnippet,
        type: LibraryType.Client,
        key: SDKKey.REACT,
    },
    {
        value: 'Node.js',
        documentationLink: `${DOC_BASE_URL}integrations/node-integration${UTM_TAGS}`,
        Snippet: NodeJSSnippet,
        type: LibraryType.Server,
        key: SDKKey.NODE_JS,
    },
    {
        value: 'Python',
        documentationLink: `${DOC_BASE_URL}integrations/python-integration${UTM_TAGS}`,
        Snippet: PythonSnippet,
        type: LibraryType.Server,
        key: SDKKey.PYTHON,
    },
    {
        value: 'Ruby',
        documentationLink: `${DOC_BASE_URL}integrations/ruby-integration${UTM_TAGS}`,
        Snippet: RubySnippet,
        type: LibraryType.Server,
        key: SDKKey.RUBY,
    },
    {
        value: 'API',
        documentationLink: `${DOC_BASE_URL}api/post-only-endpoints#example-request--response-decide-v3`,
        Snippet: APISnippet,
        type: LibraryType.Server,
        key: SDKKey.API,
    },
    {
        value: 'PHP',
        documentationLink: `${DOC_BASE_URL}integrations/php-integration${UTM_TAGS}`,
        Snippet: PHPSnippet,
        type: LibraryType.Server,
        key: SDKKey.PHP,
    },
    {
        value: 'Go',
        documentationLink: `${DOC_BASE_URL}integrations/go-integration${UTM_TAGS}`,
        Snippet: GolangSnippet,
        type: LibraryType.Server,
        key: SDKKey.GO,
    },
]

export const LOCAL_EVALUATION_LIBRARIES: string[] = [SDKKey.NODE_JS, SDKKey.PYTHON, SDKKey.RUBY, SDKKey.PHP, SDKKey.GO]

export const PAYLOAD_LIBRARIES: string[] = [SDKKey.JS_WEB, SDKKey.NODE_JS, SDKKey.PYTHON, SDKKey.RUBY, SDKKey.REACT]

export const BOOTSTRAPPING_OPTIONS: InstructionOption[] = [
    {
        value: 'JavaScript',
        documentationLink: `${DOC_BASE_URL}integrations/js-integration${UTM_TAGS}${BOOTSTRAPPING_ANCHOR}`,
        Snippet: JSBootstrappingSnippet,
        type: LibraryType.Client,
        key: SDKKey.JS_WEB,
    },
    {
        value: 'React Native',
        documentationLink: `${DOC_BASE_URL}integrate/client/react-native${UTM_TAGS}${BOOTSTRAPPING_ANCHOR}`,
        Snippet: JSBootstrappingSnippet,
        type: LibraryType.Client,
        key: SDKKey.REACT_NATIVE,
    },
]
