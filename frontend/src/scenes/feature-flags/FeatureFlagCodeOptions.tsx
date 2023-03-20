import {
    JSPayloadSnippet,
    NodeJSPayloadSnippet,
    PythonPayloadSnippet,
    RubyPayloadSnippet,
} from './FeatureFlagPayloadSnippets'
import {
    UTM_TAGS,
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
    NodeLocalEvaluationSnippet,
    PHPLocalEvaluationSnippet,
    RubyLocalEvaluationSnippet,
    PythonLocalEvaluationSnippet,
    JSBootstrappingSnippet,
    JSMultivariateSnippet,
    AndroidMultivariateSnippet,
    iOSMultivariateSnippet,
    ReactNativeMultivariateSnippet,
    PythonMultivariateSnippet,
    RubyMultivariateSnippet,
    PHPMultivariateSnippet,
    GolangMultivariateSnippet,
    NodeJSMultivariateSnippet,
} from './FeatureFlagSnippets'

const DOC_BASE_URL = 'https://posthog.com/docs/'
const FF_ANCHOR = '#feature-flags'
export const LOCAL_EVAL_ANCHOR = '#local-evaluation'
export const BOOTSTRAPPING_ANCHOR = '#bootstrapping-flags'

export interface InstructionOption {
    value: string
    documentationLink: string
    Snippet: ({ flagKey }: { flagKey: string }) => JSX.Element
    type: LibraryType
}

export enum LibraryType {
    Client = 'Client',
    Server = 'Server',
}

export const OPTIONS: InstructionOption[] = [
    {
        value: 'JavaScript',
        documentationLink: `${DOC_BASE_URL}integrations/js-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: JSSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'Android',
        documentationLink: `${DOC_BASE_URL}integrate/client/android${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: AndroidSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'iOS',
        documentationLink: `${DOC_BASE_URL}integrate/client/ios${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: iOSSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'ReactNative',
        documentationLink: `${DOC_BASE_URL}integrate/client/react-native${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: ReactNativeSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'Node.js',
        documentationLink: `${DOC_BASE_URL}integrations/node-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: NodeJSSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Python',
        documentationLink: `${DOC_BASE_URL}integrations/python-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: PythonSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Ruby',
        documentationLink: `${DOC_BASE_URL}integrations/ruby-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: RubySnippet,
        type: LibraryType.Server,
    },
    {
        value: 'API',
        documentationLink: `${DOC_BASE_URL}api/post-only-endpoints#example-request--response-decide-v2`,
        Snippet: APISnippet,
        type: LibraryType.Server,
    },
    {
        value: 'PHP',
        documentationLink: `${DOC_BASE_URL}integrations/php-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: PHPSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Golang',
        documentationLink: `${DOC_BASE_URL}integrations/go-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: GolangSnippet,
        type: LibraryType.Server,
    },
]

export const MULTIVARIATE_OPTIONS: InstructionOption[] = [
    {
        value: 'JavaScript',
        documentationLink: `${DOC_BASE_URL}integrations/js-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: JSMultivariateSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'Android',
        documentationLink: `${DOC_BASE_URL}integrate/client/android${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: AndroidMultivariateSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'iOS',
        documentationLink: `${DOC_BASE_URL}integrate/client/ios${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: iOSMultivariateSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'ReactNative',
        documentationLink: `${DOC_BASE_URL}integrate/client/react-native${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: ReactNativeMultivariateSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'Node.js',
        documentationLink: `${DOC_BASE_URL}integrations/node-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: NodeJSMultivariateSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Python',
        documentationLink: `${DOC_BASE_URL}integrations/python-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: PythonMultivariateSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Ruby',
        documentationLink: `${DOC_BASE_URL}integrations/ruby-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: RubyMultivariateSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'API',
        documentationLink: `${DOC_BASE_URL}api/post-only-endpoints#example-request--response-decide-v2`,
        Snippet: APISnippet,
        type: LibraryType.Server,
    },
    {
        value: 'PHP',
        documentationLink: `${DOC_BASE_URL}integrations/php-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: PHPMultivariateSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Golang',
        documentationLink: `${DOC_BASE_URL}integrations/go-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: GolangMultivariateSnippet,
        type: LibraryType.Server,
    },
]

export const PAYLOAD_OPTIONS: InstructionOption[] = [
    {
        value: 'JavaScript',
        documentationLink: `${DOC_BASE_URL}integrations/js-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: JSPayloadSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'Node.js',
        documentationLink: `${DOC_BASE_URL}integrations/node-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: NodeJSPayloadSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Python',
        documentationLink: `${DOC_BASE_URL}integrations/python-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: PythonPayloadSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Ruby',
        documentationLink: `${DOC_BASE_URL}integrations/ruby-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: RubyPayloadSnippet,
        type: LibraryType.Server,
    },
]

export const LOCAL_EVALUATION_OPTIONS: InstructionOption[] = [
    {
        value: 'Node.js',
        documentationLink: `${DOC_BASE_URL}integrations/node-integration${UTM_TAGS}${LOCAL_EVAL_ANCHOR}`,
        Snippet: NodeLocalEvaluationSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'PHP',
        documentationLink: `${DOC_BASE_URL}integrations/php-integration${UTM_TAGS}${LOCAL_EVAL_ANCHOR}`,
        Snippet: PHPLocalEvaluationSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Ruby',
        documentationLink: `${DOC_BASE_URL}integrations/ruby-integration${UTM_TAGS}${LOCAL_EVAL_ANCHOR}`,
        Snippet: RubyLocalEvaluationSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Golang',
        documentationLink: `${DOC_BASE_URL}integrations/go-integration${UTM_TAGS}${LOCAL_EVAL_ANCHOR}`,
        Snippet: GolangSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Python',
        documentationLink: `${DOC_BASE_URL}integrations/python-integration${UTM_TAGS}${LOCAL_EVAL_ANCHOR}`,
        Snippet: PythonLocalEvaluationSnippet,
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
        value: 'ReactNative',
        documentationLink: `${DOC_BASE_URL}integrate/client/react-native${UTM_TAGS}${BOOTSTRAPPING_ANCHOR}`,
        Snippet: JSBootstrappingSnippet,
        type: LibraryType.Client,
    },
]
