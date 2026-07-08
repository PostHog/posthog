import { useState } from 'react'

import { IconServer } from '@posthog/icons'
import { IconFlutter, IconGo, IconJavascript, IconPHP, IconPython, IconRuby } from '@posthog/icons'
import { LemonSelect, LemonTabs, Link } from '@posthog/lemon-ui'

import { IconAndroidOS, IconAppleIOS, IconNodeJS } from 'lib/lemon-ui/icons'

import { Experiment, MultivariateFlagVariant, SDKKey } from '~/types'

import {
    AndroidSnippet,
    FlutterSnippet,
    GolangSnippet,
    IOSSnippet,
    JSSnippet,
    JavaSnippet,
    NodeJSSnippet,
    PHPSnippet,
    PromptExperimentAgentPromptSnippet,
    PromptExperimentJSSnippet,
    PromptExperimentPythonSnippet,
    PythonSnippet,
    RNSnippet,
    ReactSnippet,
    RubySnippet,
} from './ExperimentCodeSnippets'
import { getExperimentVariants } from './utils'

interface ExperimentImplementationDetailsProps {
    experiment: Partial<Experiment> | null
}

const UTM_TAGS = '?utm_medium=in-product&utm_campaign=experiment'
const DOC_BASE_URL = 'https://posthog.com/docs/'
const FF_ANCHOR = '#feature-flags'

export enum LibraryType {
    Client = 'Client',
    Server = 'Server',
}

export const OPTIONS = [
    {
        value: 'JavaScript',
        key: SDKKey.JS_WEB,
        documentationLink: `${DOC_BASE_URL}libraries/js${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconJavascript,
        Snippet: JSSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'Android',
        key: SDKKey.ANDROID,
        documentationLink: `${DOC_BASE_URL}libraries/android${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconAndroidOS,
        Snippet: AndroidSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'Go',
        key: SDKKey.GO,
        documentationLink: `${DOC_BASE_URL}libraries/go${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconGo,
        Snippet: GolangSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Flutter',
        key: SDKKey.FLUTTER,
        documentationLink: `${DOC_BASE_URL}libraries/flutter${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconFlutter,
        Snippet: FlutterSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'iOS',
        key: SDKKey.IOS,
        documentationLink: `${DOC_BASE_URL}libraries/ios${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconAppleIOS,
        Snippet: IOSSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'Node.js',
        key: SDKKey.NODE_JS,
        documentationLink: `${DOC_BASE_URL}libraries/node${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconNodeJS,
        Snippet: NodeJSSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'PHP',
        key: SDKKey.PHP,
        documentationLink: `${DOC_BASE_URL}libraries/php${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconPHP,
        Snippet: PHPSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Python',
        key: SDKKey.PYTHON,
        documentationLink: `${DOC_BASE_URL}libraries/python${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconPython,
        Snippet: PythonSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'React',
        key: SDKKey.REACT,
        documentationLink: `${DOC_BASE_URL}libraries/react${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconJavascript,
        Snippet: ReactSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'ReactNative',
        key: SDKKey.REACT_NATIVE,
        documentationLink: `${DOC_BASE_URL}libraries/react-native${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconJavascript,
        Snippet: RNSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'Ruby',
        key: SDKKey.RUBY,
        documentationLink: `${DOC_BASE_URL}libraries/ruby${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconRuby,
        Snippet: RubySnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Java',
        key: SDKKey.JAVA,
        documentationLink: `${DOC_BASE_URL}libraries/java${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconServer,
        Snippet: JavaSnippet,
        type: LibraryType.Server,
    },
]

export function CodeLanguageSelect({
    selectedOptionValue,
    selectOption,
}: {
    selectedOptionValue: string
    selectOption: (selectedValue: string) => void
}): JSX.Element {
    return (
        <LemonSelect
            size="small"
            className="min-w-[7.5rem]"
            onSelect={selectOption}
            value={selectedOptionValue}
            options={[
                {
                    title: 'Client libraries',
                    options: OPTIONS.filter((option) => option.type == LibraryType.Client).map(({ Icon, value }) => ({
                        value,
                        label: value,
                        labelInMenu: (
                            <div className="flex items-center deprecated-space-x-2">
                                <Icon />
                                <span>{value}</span>
                            </div>
                        ),
                    })),
                },
                {
                    title: 'Server libraries',
                    options: OPTIONS.filter((option) => option.type == LibraryType.Server).map(({ Icon, value }) => ({
                        value,
                        label: value,
                        labelInMenu: (
                            <div className="flex items-center deprecated-space-x-2">
                                <Icon />
                                <span>{value}</span>
                            </div>
                        ),
                    })),
                },
            ]}
        />
    )
}

type PromptImplementationTab = 'agent' | 'python' | 'javascript'

function PromptExperimentImplementation({
    flagKey,
    promptMetadata,
}: {
    flagKey: string
    promptMetadata: NonNullable<NonNullable<Experiment['parameters']>['prompt_metadata']>
}): JSX.Element {
    const [activeTab, setActiveTab] = useState<PromptImplementationTab>('agent')
    return (
        <div className="mb-4">
            <div className="border rounded bg-surface-primary">
                <div className="p-6 deprecated-space-y-4">
                    <div className="text-secondary text-sm">
                        Prompt experiment for <b>{promptMetadata.name}</b>{' '}
                        <span className="text-muted">({promptMetadata.templates.join(', ')})</span>
                    </div>
                    <div>
                        <div className="mb-1">
                            <b>Wire up the experiment in your code</b>
                        </div>
                        <p className="text-secondary text-xs">
                            Each variant carries a <code>{`{prompt_name, prompt_version}`}</code> payload on the feature
                            flag, so the SDK reads the right version via <code>flags.get_flag_payload(...)</code>. The
                            PostHog AI wrapper auto-emits <code>$ai_generation</code> tagged with{' '}
                            <code>$ai_prompt_name</code>, which is how the experiment metric attributes results.
                        </p>
                        <LemonTabs
                            activeKey={activeTab}
                            onChange={(key) => setActiveTab(key as PromptImplementationTab)}
                            tabs={[
                                {
                                    key: 'agent',
                                    label: 'Agent prompt',
                                    content: (
                                        <>
                                            <p className="text-secondary text-xs mb-2">
                                                Copy this and paste it into your AI coding assistant (Cursor, Claude
                                                Code, ChatGPT, …) to wire up the experiment in your project's framework
                                                and style. Language-agnostic; the agent figures out the SDK.
                                            </p>
                                            <PromptExperimentAgentPromptSnippet flagKey={flagKey} />
                                        </>
                                    ),
                                },
                                {
                                    key: 'python',
                                    label: 'Python',
                                    content: <PromptExperimentPythonSnippet flagKey={flagKey} />,
                                },
                                {
                                    key: 'javascript',
                                    label: 'JavaScript',
                                    content: <PromptExperimentJSSnippet flagKey={flagKey} />,
                                },
                            ]}
                        />
                        <Link subtle to="https://posthog.com/docs/prompt-management" target="_blank">
                            See the docs for prompt management.
                        </Link>
                    </div>
                </div>
            </div>
        </div>
    )
}

function GenericExperimentImplementation({ experiment }: ExperimentImplementationDetailsProps): JSX.Element {
    const defaultVariant = getExperimentVariants(experiment)[1]?.key ?? 'test'
    const [currentVariant, setCurrentVariant] = useState(defaultVariant)
    const [defaultSelectedOption] = OPTIONS
    const [selectedOption, setSelectedOption] = useState(defaultSelectedOption)

    const selectOption = (selectedValue: string): void => {
        const option = OPTIONS.find((option) => option.value === selectedValue)

        if (option) {
            setSelectedOption(option)
        }
    }

    return (
        <div className="mb-4">
            <div className="border rounded bg-surface-primary">
                <div className="p-6 deprecated-space-y-4">
                    <div className="flex justify-between">
                        <div className="flex items-center">
                            <span className="mr-2">Variant group</span>
                            <LemonSelect
                                size="small"
                                className="min-w-[5rem]"
                                onSelect={setCurrentVariant}
                                value={currentVariant}
                                options={getExperimentVariants(experiment).map((variant: MultivariateFlagVariant) => ({
                                    value: variant.key,
                                    label: variant.key,
                                }))}
                            />
                        </div>
                        <div>
                            <CodeLanguageSelect
                                selectOption={selectOption}
                                selectedOptionValue={selectedOption.value}
                            />
                        </div>
                    </div>
                    <div>
                        <div className="mb-1">
                            <b>Implement your experiment in code</b>
                        </div>
                        <div className="mb-1">
                            <selectedOption.Snippet
                                variant={currentVariant}
                                flagKey={experiment?.feature_flag?.key ?? ''}
                            />
                        </div>

                        <Link subtle to={selectedOption.documentationLink} target="_blank">
                            See the docs for more implementation information.
                        </Link>
                    </div>
                </div>
            </div>
        </div>
    )
}

export function ExperimentImplementationDetails({ experiment }: ExperimentImplementationDetailsProps): JSX.Element {
    const promptMetadata = experiment?.parameters?.prompt_metadata

    if (promptMetadata) {
        return (
            <PromptExperimentImplementation
                flagKey={experiment?.feature_flag?.key ?? ''}
                promptMetadata={promptMetadata}
            />
        )
    }

    return <GenericExperimentImplementation experiment={experiment} />
}
