import posthog from 'posthog-js'
import { useState } from 'react'

import { IconServer } from '@posthog/icons'
import { IconFlutter, IconGo, IconJavascript, IconPHP, IconPython, IconRuby } from '@posthog/icons'
import { LemonSelect, LemonTabs, Link } from '@posthog/lemon-ui'

import { IconAndroidOS, IconAppleIOS, IconNodeJS } from 'lib/lemon-ui/icons'

import { Experiment, MultivariateFlagVariant, SDKKey } from '~/types'

import { getExperimentStatus } from 'products/experiments/frontend/experimentStatus'

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

/** Where the snippet is shown: above the tabs while the experiment is a draft, or in the Code tab. */
export type ImplementationSnippetPlacement = 'draft_header' | 'code_tab'

interface ExperimentImplementationDetailsProps {
    experiment: Partial<Experiment> | null
    placement: ImplementationSnippetPlacement
}

interface SnippetCopy {
    sdk: SDKKey | null
    variant: string | null
    /** `test_override` is the "Test that it works" line, which forces a variant in the user's own browser. */
    snippetKind: 'code' | 'test_override'
}

type OnSnippetCopied = (copy: SnippetCopy) => void

function reportImplementationSnippetCopied(
    experiment: Partial<Experiment> | null,
    placement: ImplementationSnippetPlacement,
    { sdk, variant, snippetKind }: SnippetCopy
): void {
    posthog.capture('experiment implementation snippet copied', {
        experiment_id: experiment?.id,
        experiment_status: getExperimentStatus(experiment),
        placement,
        sdk,
        variant,
        snippet_kind: snippetKind,
    })
}

// Agent prompt copies get their own event, so they never count as code copies.
function reportAgentPromptCopied(
    experiment: Partial<Experiment> | null,
    placement: ImplementationSnippetPlacement
): void {
    posthog.capture('experiment implementation agent prompt copied', {
        experiment_id: experiment?.id,
        experiment_status: getExperimentStatus(experiment),
        placement,
        prompt_kind: 'prompt_experiment',
        source: 'prompt_text',
    })
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
                            <div className="flex items-center gap-2">
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
                            <div className="flex items-center gap-2">
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
    onSnippetCopied,
    onAgentPromptCopied,
}: {
    flagKey: string
    promptMetadata: NonNullable<NonNullable<Experiment['parameters']>['prompt_metadata']>
    onSnippetCopied: OnSnippetCopied
    onAgentPromptCopied: () => void
}): JSX.Element {
    const [activeTab, setActiveTab] = useState<PromptImplementationTab>('agent')
    return (
        <div className="space-y-4">
            <div>
                <h2 className="font-semibold text-lg mb-0">Implementation</h2>
                <div className="text-secondary text-sm">
                    Prompt experiment for <b>{promptMetadata.name}</b>{' '}
                    <span className="text-muted">({promptMetadata.templates.join(', ')})</span>
                </div>
            </div>
            <div>
                <p className="text-secondary text-xs">
                    Each variant carries a <code>{`{prompt_name, prompt_version}`}</code> payload on the feature flag,
                    so the SDK reads the right version via <code>flags.get_flag_payload(...)</code>. The PostHog AI
                    wrapper auto-emits <code>$ai_generation</code> tagged with <code>$ai_prompt_name</code>, which is
                    how the experiment metric attributes results.
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
                                        Copy this and paste it into your AI coding assistant (Cursor, Claude Code,
                                        ChatGPT, …) to wire up the experiment in your project's framework and style.
                                        Language-agnostic; the agent figures out the SDK.
                                    </p>
                                    <PromptExperimentAgentPromptSnippet
                                        flagKey={flagKey}
                                        onCopy={onAgentPromptCopied}
                                    />
                                </>
                            ),
                        },
                        {
                            key: 'python',
                            label: 'Python',
                            content: (
                                <PromptExperimentPythonSnippet
                                    flagKey={flagKey}
                                    onCopy={() =>
                                        onSnippetCopied({ sdk: SDKKey.PYTHON, variant: null, snippetKind: 'code' })
                                    }
                                />
                            ),
                        },
                        {
                            key: 'javascript',
                            label: 'JavaScript',
                            content: (
                                <PromptExperimentJSSnippet
                                    flagKey={flagKey}
                                    onCopy={() =>
                                        onSnippetCopied({ sdk: SDKKey.NODE_JS, variant: null, snippetKind: 'code' })
                                    }
                                />
                            ),
                        },
                    ]}
                />
                <Link subtle to="https://posthog.com/docs/prompt-management" target="_blank">
                    See the docs for prompt management.
                </Link>
            </div>
        </div>
    )
}

function GenericExperimentImplementation({
    experiment,
    onSnippetCopied,
}: {
    experiment: Partial<Experiment> | null
    onSnippetCopied: OnSnippetCopied
}): JSX.Element {
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
        <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="font-semibold text-lg mb-0">Implementation</h2>
                <div className="flex items-center gap-4">
                    <div className="flex items-center gap-2">
                        <span className="text-secondary text-sm">Variant group</span>
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
                    <CodeLanguageSelect selectOption={selectOption} selectedOptionValue={selectedOption.value} />
                </div>
            </div>
            <div>
                <div className="mb-2">
                    <selectedOption.Snippet
                        variant={currentVariant}
                        flagKey={experiment?.feature_flag?.key ?? ''}
                        onCopy={() =>
                            onSnippetCopied({ sdk: selectedOption.key, variant: currentVariant, snippetKind: 'code' })
                        }
                        onTestCopy={() =>
                            onSnippetCopied({
                                sdk: selectedOption.key,
                                variant: currentVariant,
                                snippetKind: 'test_override',
                            })
                        }
                    />
                </div>
                <Link subtle to={selectedOption.documentationLink} target="_blank">
                    See the docs for more implementation information.
                </Link>
            </div>
        </div>
    )
}

export function ExperimentImplementationDetails({
    experiment,
    placement,
}: ExperimentImplementationDetailsProps): JSX.Element {
    const promptMetadata = experiment?.parameters?.prompt_metadata
    const onSnippetCopied: OnSnippetCopied = (copy) => reportImplementationSnippetCopied(experiment, placement, copy)

    if (promptMetadata) {
        return (
            <PromptExperimentImplementation
                flagKey={experiment?.feature_flag?.key ?? ''}
                promptMetadata={promptMetadata}
                onSnippetCopied={onSnippetCopied}
                onAgentPromptCopied={() => reportAgentPromptCopied(experiment, placement)}
            />
        )
    }

    return <GenericExperimentImplementation experiment={experiment} onSnippetCopied={onSnippetCopied} />
}
