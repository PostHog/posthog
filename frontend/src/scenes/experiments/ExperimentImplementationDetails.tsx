import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconServer } from '@posthog/icons'
import { IconFlutter, IconGo, IconJavascript, IconPHP, IconPython, IconRuby } from '@posthog/icons'
import { LemonSegmentedButton, LemonSelect, LemonTabs, Link } from '@posthog/lemon-ui'

import { type AgentPromptAction, AgentPromptButton, buildAgentPrompt } from 'lib/components/AgentPromptButton'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconAndroidOS, IconAppleIOS, IconNodeJS } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { ExperimentExposureConfig } from '~/queries/schema/schema-general'
import { Experiment, GroupType, GroupTypeIndex, MultivariateFlagVariant, SDKKey } from '~/types'

import { getExperimentStatus } from 'products/experiments/frontend/experimentStatus'

import {
    AndroidSnippet,
    buildExperimentFlagAgentPrompt,
    type ExperimentAgentPromptEvent,
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
import { EXPERIMENT_EXPOSURE_EVENT, EXPOSURE_DEFAULT_EVENT, getActivationConfig } from './exposureContract'
import { getBaselineVariantKey, getExperimentVariants } from './utils'

/** Where the snippet is shown: above the tabs while the experiment is a draft, or in the Code tab. */
export type ImplementationSnippetPlacement = 'draft_header' | 'code_tab'

/** The arm of the EXPERIMENT_IMPLEMENTATION_AGENT_PROMPT experiment the generic section rendered. */
export type ImplementationArm = 'control' | 'test'

type ImplementationOption = 'agent_prompt' | 'code_snippet'

// The test arm opens on the prompt, so the experiment measures what leading with the prompt does.
const DEFAULT_IMPLEMENTATION_OPTION: ImplementationOption = 'agent_prompt'

// The test arm opens the agent prompt and long code snippets on a preview, so they don't push the page down.
// It stops after the prompt's context lines.
const IMPLEMENTATION_PREVIEW_LINES = 8

interface ExperimentImplementationDetailsProps {
    experiment: Partial<Experiment> | null
    placement: ImplementationSnippetPlacement
}

interface SnippetCopy {
    sdk: SDKKey | null
    variant: string | null
    /** `test_override` is the "Test that it works" line, which forces a variant in the user's own browser. */
    snippetKind: 'code' | 'test_override'
    /** Null for prompt experiments, which the implementation experiment leaves out. */
    implementationArm: ImplementationArm | null
}

type OnSnippetCopied = (copy: SnippetCopy) => void

function reportImplementationSnippetCopied(
    experiment: Partial<Experiment> | null,
    placement: ImplementationSnippetPlacement,
    { sdk, variant, snippetKind, implementationArm }: SnippetCopy
): void {
    posthog.capture('experiment implementation snippet copied', {
        experiment_id: experiment?.id,
        experiment_status: getExperimentStatus(experiment),
        placement,
        sdk,
        variant,
        snippet_kind: snippetKind,
        implementation_arm: implementationArm,
    })
}

interface AgentPromptCopy {
    /** `prompt_experiment` is a prompt experiment's prompt, `feature_flag` is the implementation experiment's. */
    promptKind: 'prompt_experiment' | 'feature_flag'
    /** `prompt_text` is the copy button on the prompt, `agent_button` is the agent button's Clipboard option. */
    source: 'prompt_text' | 'agent_button'
}

type OnAgentPromptCopied = (copy: AgentPromptCopy) => void

// Agent prompt copies get their own event, so they never count as code copies.
function reportAgentPromptCopied(
    experiment: Partial<Experiment> | null,
    placement: ImplementationSnippetPlacement,
    { promptKind, source }: AgentPromptCopy
): void {
    posthog.capture('experiment implementation agent prompt copied', {
        experiment_id: experiment?.id,
        experiment_status: getExperimentStatus(experiment),
        placement,
        prompt_kind: promptKind,
        source,
    })
}

/** The event or action an exposure config names, or null when it is the default exposure the flag read records. */
function promptEvent(config: ExperimentExposureConfig | undefined): ExperimentAgentPromptEvent | null {
    if (!config) {
        return null
    }
    if ('event' in config) {
        return [EXPOSURE_DEFAULT_EVENT, EXPERIMENT_EXPOSURE_EVENT].includes(config.event)
            ? null
            : { kind: 'event', name: config.event }
    }
    return { kind: 'action', name: config.name ?? String(config.id) }
}

function experimentFlagAgentPrompt(
    experiment: Partial<Experiment> | null,
    groupTypes: Map<GroupTypeIndex, GroupType>
): string {
    const experimentId = experiment?.id
    const groupTypeIndex = experiment?.feature_flag?.filters?.aggregation_group_type_index
    return buildExperimentFlagAgentPrompt({
        experimentName: experiment?.name ?? '',
        experimentUrl:
            typeof experimentId === 'number'
                ? window.location.origin + addProjectIdIfMissing(urls.experiment(experimentId))
                : null,
        flagKey: experiment?.feature_flag?.key ?? '',
        variantKeys: getExperimentVariants(experiment).map((variant) => variant.key),
        baselineVariantKey: getBaselineVariantKey(experiment),
        customExposure: promptEvent(experiment?.exposure_criteria?.exposure_config),
        activation: promptEvent(getActivationConfig(experiment?.exposure_criteria)),
        groupType:
            groupTypeIndex != null ? (groupTypes.get(groupTypeIndex as GroupTypeIndex)?.group_type ?? null) : null,
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
                                        onSnippetCopied({
                                            sdk: SDKKey.PYTHON,
                                            variant: null,
                                            snippetKind: 'code',
                                            implementationArm: null,
                                        })
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
                                        onSnippetCopied({
                                            sdk: SDKKey.NODE_JS,
                                            variant: null,
                                            snippetKind: 'code',
                                            implementationArm: null,
                                        })
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

function ExperimentAgentPrompt({
    action,
    onPromptCopied,
}: {
    action: AgentPromptAction
    onPromptCopied: () => void
}): JSX.Element {
    const { currentProjectId } = useValues(projectLogic)
    const { isCloudOrDev } = useValues(preflightLogic)
    // Show the text the Clipboard option copies, so it also says how to install the PostHog MCP server.
    const prompt = buildAgentPrompt(action, 'clipboard', currentProjectId, !!isCloudOrDev)

    return (
        <div className="space-y-2">
            <p className="text-secondary text-sm mb-0">
                Run this prompt in your coding agent to add the feature flag to your code.
            </p>
            <CodeSnippet
                language={Language.Text}
                wrap
                compact
                onCopy={onPromptCopied}
                maxLinesWithoutExpansion={IMPLEMENTATION_PREVIEW_LINES}
            >
                {prompt}
            </CodeSnippet>
        </div>
    )
}

function GenericExperimentImplementation({
    experiment,
    placement,
    onSnippetCopied,
    onAgentPromptCopied,
}: {
    experiment: Partial<Experiment> | null
    placement: ImplementationSnippetPlacement
    onSnippetCopied: OnSnippetCopied
    onAgentPromptCopied: OnAgentPromptCopied
}): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { groupTypes } = useValues(groupsModel)
    // Read here rather than on the page, so only people who see this section are exposed to the experiment.
    const implementationArm: ImplementationArm =
        featureFlags[FEATURE_FLAGS.EXPERIMENT_IMPLEMENTATION_AGENT_PROMPT] === 'test' ? 'test' : 'control'
    const [implementationOption, setImplementationOption] =
        useState<ImplementationOption>(DEFAULT_IMPLEMENTATION_OPTION)
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

    const selectImplementationOption = (option: ImplementationOption): void => {
        if (option === implementationOption) {
            return
        }
        setImplementationOption(option)
        posthog.capture('experiment implementation option selected', {
            experiment_id: experiment?.id,
            placement,
            option,
        })
    }

    const reportAgentPromptOpened = (agent: string): void => {
        posthog.capture('experiment implementation agent prompt opened', {
            experiment_id: experiment?.id,
            placement,
            agent,
        })
    }

    const agentPromptAction: AgentPromptAction = {
        key: 'implement',
        label: 'prompt',
        buildPrompt: () => experimentFlagAgentPrompt(experiment, groupTypes),
    }
    const reportFlagAgentPromptCopied = (source: AgentPromptCopy['source']): void =>
        onAgentPromptCopied({ promptKind: 'feature_flag', source })

    const snippetSelects = (
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
    )

    const snippet = (
        <div>
            <div className="mb-2">
                <selectedOption.Snippet
                    variant={currentVariant}
                    flagKey={experiment?.feature_flag?.key ?? ''}
                    // The control arm keeps today's full snippet.
                    maxLinesWithoutExpansion={implementationArm === 'test' ? IMPLEMENTATION_PREVIEW_LINES : undefined}
                    onCopy={() =>
                        onSnippetCopied({
                            sdk: selectedOption.key,
                            variant: currentVariant,
                            snippetKind: 'code',
                            implementationArm,
                        })
                    }
                    onTestCopy={() =>
                        onSnippetCopied({
                            sdk: selectedOption.key,
                            variant: currentVariant,
                            snippetKind: 'test_override',
                            implementationArm,
                        })
                    }
                />
            </div>
            <Link subtle to={selectedOption.documentationLink} target="_blank">
                See the docs for more implementation information.
            </Link>
        </div>
    )

    if (implementationArm === 'control') {
        return (
            <div className="space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <h2 className="font-semibold text-lg mb-0">Implementation</h2>
                    {snippetSelects}
                </div>
                {snippet}
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="font-semibold text-lg mb-0">Implementation</h2>
                {/* Each option's controls sit left of the switch, so the switch stays put on a change. */}
                <div className="flex flex-wrap items-center gap-2">
                    {implementationOption === 'agent_prompt' ? (
                        <AgentPromptButton
                            appearance="lemon"
                            pinnedAgentKey="clipboard"
                            // PostHog AI cannot edit the user's codebase, so it cannot add the flag.
                            excludeAgentKeys={['posthog-ai']}
                            data-attr="experiment-implementation-agent-prompt"
                            actions={[agentPromptAction]}
                            onRun={({ agentKey }) =>
                                agentKey === 'clipboard'
                                    ? reportFlagAgentPromptCopied('agent_button')
                                    : reportAgentPromptOpened(agentKey)
                            }
                        />
                    ) : (
                        snippetSelects
                    )}
                    <LemonSegmentedButton
                        size="small"
                        value={implementationOption}
                        onChange={selectImplementationOption}
                        options={[
                            { value: 'agent_prompt', label: 'Prompt for your agent' },
                            { value: 'code_snippet', label: 'Code snippet' },
                        ]}
                    />
                </div>
            </div>
            {implementationOption === 'agent_prompt' ? (
                <ExperimentAgentPrompt
                    action={agentPromptAction}
                    onPromptCopied={() => reportFlagAgentPromptCopied('prompt_text')}
                />
            ) : (
                snippet
            )}
        </div>
    )
}

export function ExperimentImplementationDetails({
    experiment,
    placement,
}: ExperimentImplementationDetailsProps): JSX.Element {
    const promptMetadata = experiment?.parameters?.prompt_metadata
    const onSnippetCopied: OnSnippetCopied = (copy) => reportImplementationSnippetCopied(experiment, placement, copy)
    const onAgentPromptCopied: OnAgentPromptCopied = (copy) => reportAgentPromptCopied(experiment, placement, copy)

    if (promptMetadata) {
        return (
            <PromptExperimentImplementation
                flagKey={experiment?.feature_flag?.key ?? ''}
                promptMetadata={promptMetadata}
                onSnippetCopied={onSnippetCopied}
                onAgentPromptCopied={() =>
                    onAgentPromptCopied({ promptKind: 'prompt_experiment', source: 'prompt_text' })
                }
            />
        )
    }

    return (
        <GenericExperimentImplementation
            experiment={experiment}
            placement={placement}
            onSnippetCopied={onSnippetCopied}
            onAgentPromptCopied={onAgentPromptCopied}
        />
    )
}
