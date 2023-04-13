import {
    JSPayloadSnippet,
    NodeJSPayloadSnippet,
    PythonPayloadSnippet,
    RubyPayloadSnippet,
} from './FeatureFlagPayloadSnippets'
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
    },
    {
        value: 'Android',
        documentationLink: `${DOC_BASE_URL}integrate/client/android${UTM_TAGS}`,
        Snippet: AndroidSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'iOS',
        documentationLink: `${DOC_BASE_URL}integrate/client/ios${UTM_TAGS}`,
        Snippet: iOSSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'React Native',
        documentationLink: `${DOC_BASE_URL}integrate/client/react-native${UTM_TAGS}`,
        Snippet: ReactNativeSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'Node.js',
        documentationLink: `${DOC_BASE_URL}integrations/node-integration${UTM_TAGS}`,
        Snippet: NodeJSSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Python',
        documentationLink: `${DOC_BASE_URL}integrations/python-integration${UTM_TAGS}`,
        Snippet: PythonSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Ruby',
        documentationLink: `${DOC_BASE_URL}integrations/ruby-integration${UTM_TAGS}`,
        Snippet: RubySnippet,
        type: LibraryType.Server,
    },
    {
        value: 'API',
        documentationLink: `${DOC_BASE_URL}api/post-only-endpoints#example-request--response-decide-v3`,
        Snippet: APISnippet,
        type: LibraryType.Server,
    },
    {
        value: 'PHP',
        documentationLink: `${DOC_BASE_URL}integrations/php-integration${UTM_TAGS}`,
        Snippet: PHPSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Golang',
        documentationLink: `${DOC_BASE_URL}integrations/go-integration${UTM_TAGS}`,
        Snippet: GolangSnippet,
        type: LibraryType.Server,
    },
]

export const LOCAL_EVALUATION_LIBRARIES: string[] = ['Node.js', 'Python', 'Ruby', 'PHP', 'Golang']

export const PAYLOAD_LIBRARIES: string[] = ['JavaScript', 'Node.js', 'Python', 'Ruby']

export const PAYLOAD_OPTIONS: InstructionOption[] = [
    {
        value: 'JavaScript',
        documentationLink: `${DOC_BASE_URL}integrations/js-integration${UTM_TAGS}${PAYLOADS_ANCHOR}`,
        Snippet: JSPayloadSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'Node.js',
        documentationLink: `${DOC_BASE_URL}integrations/node-integration${UTM_TAGS}${PAYLOADS_ANCHOR}`,
        Snippet: NodeJSPayloadSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Python',
        documentationLink: `${DOC_BASE_URL}integrations/python-integration${UTM_TAGS}${PAYLOADS_ANCHOR}`,
        Snippet: PythonPayloadSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Ruby',
        documentationLink: `${DOC_BASE_URL}integrations/ruby-integration${UTM_TAGS}${PAYLOADS_ANCHOR}`,
        Snippet: RubyPayloadSnippet,
        type: LibraryType.Server,
    },
]

export const BOOTSTRAPPING_OPTIONS: InstructionOption[] = [
    {
        value: 'JavaScript',
        documentationLink: `${DOC_BASE_URL}integrations/js-integration${UTM_TAGS}${BOOTSTRAPPING_ANCHOR}`,
        Snippet: JSBootstrappingSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'React Native',
        documentationLink: `${DOC_BASE_URL}integrate/client/react-native${UTM_TAGS}${BOOTSTRAPPING_ANCHOR}`,
        Snippet: JSBootstrappingSnippet,
        type: LibraryType.Client,
    },
]
