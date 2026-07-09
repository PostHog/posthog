import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { Suspense, useRef } from 'react'

import { IconColumns, IconMarkdown, IconMarkdownFilled } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonModal,
    LemonSelect,
    LemonTabs,
    LemonTag,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { lazyWithRetry } from 'lib/utils/lazyWithRetry'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { Query } from '~/queries/Query/Query'
import { AccessControlLevel, AccessControlResourceType, LLMPrompt, LLMPromptVersionSummary } from '~/types'

import type { ExperimentBasicApi } from '../../../experiments/frontend/generated/api.schemas'
import { useTracesQueryContext } from '../AIObservabilityTracesScene'
import { MarkdownOutline } from '../components/MarkdownOutline'
import { CreatePromptExperimentModal } from './CreatePromptExperimentModal'
import { createPromptExperimentModalLogic } from './createPromptExperimentModalLogic'
import { PromptAnalyticsScope, isPrompt, llmPromptLogic } from './llmPromptLogic'
import { promptExperimentsLogic } from './promptExperimentsLogic'
import { PROMPT_NAME_MAX_LENGTH } from './utils'

const MonacoDiffEditor = lazyWithRetry(() => import('lib/components/MonacoDiffEditor'))

function PromptOutline({
    promptText,
    containerRef,
    className,
}: {
    promptText: string
    containerRef: React.RefObject<HTMLDivElement | null>
    className?: string
}): JSX.Element | null {
    const { isOutlineExpanded } = useValues(llmPromptLogic)
    const { toggleOutlineExpanded } = useActions(llmPromptLogic)

    return (
        <MarkdownOutline
            markdownText={promptText}
            containerRef={containerRef}
            className={className}
            label="Prompt outline"
            tooltipText="Navigate the sections of your prompt. Click a heading to scroll to it."
            dataAttrPrefix="llma-prompt"
            isExpanded={isOutlineExpanded}
            onToggleExpanded={toggleOutlineExpanded}
        />
    )
}

export function PromptViewDetails(): JSX.Element {
    const { prompt, isRenderingMarkdown, isDiffVisible, canCompareVersions, compareVersionOptions } =
        useValues(llmPromptLogic)
    const { toggleMarkdownRendering, setCompareVersion } = useActions(llmPromptLogic)
    const markdownContainerRef = useRef<HTMLDivElement>(null)

    if (!prompt || !isPrompt(prompt)) {
        return <></>
    }

    const promptText = prompt.prompt
    const variableMatches = promptText.match(/\{\{([^}]+)\}\}/g)
    const variables = variableMatches
        ? [...new Set(variableMatches.map((match: string) => match.slice(2, -2).trim()))]
        : []

    return (
        <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2">
                <LemonTag type="highlight" size="small">
                    v{prompt.version}
                </LemonTag>
                {prompt.is_latest ? (
                    <LemonTag type="success" size="small">
                        Latest
                    </LemonTag>
                ) : (
                    <LemonTag type="muted" size="small">
                        Historical
                    </LemonTag>
                )}
                <span className="text-secondary text-sm">
                    This prompt has {prompt.version_count} published version{prompt.version_count === 1 ? '' : 's'}.
                </span>
            </div>

            {prompt.version_description ? (
                <p className="text-secondary m-0 text-sm italic" data-attr="llma-prompt-version-description">
                    {prompt.version_description}
                </p>
            ) : null}

            <div>
                <label className="text-xs font-semibold uppercase text-secondary">Name</label>
                <p className="font-mono">{prompt.name}</p>
            </div>

            <div>
                <div className="flex items-center gap-2">
                    <label className="text-xs font-semibold uppercase text-secondary">Prompt</label>
                    {!isDiffVisible && (
                        <LemonButton
                            size="small"
                            noPadding
                            icon={isRenderingMarkdown ? <IconMarkdownFilled /> : <IconMarkdown />}
                            tooltip="Toggle markdown rendering"
                            onClick={toggleMarkdownRendering}
                        />
                    )}
                    {canCompareVersions && (
                        <LemonButton
                            size="xsmall"
                            type={isDiffVisible ? 'primary' : 'secondary'}
                            icon={<IconColumns />}
                            onClick={() => {
                                if (isDiffVisible) {
                                    setCompareVersion(null)
                                } else {
                                    const firstOption = compareVersionOptions[0]?.value
                                    const defaultVersion = compareVersionOptions.some(
                                        (o) => o.value === prompt.version - 1
                                    )
                                        ? prompt.version - 1
                                        : (firstOption ?? null)
                                    setCompareVersion(defaultVersion)
                                }
                            }}
                            data-attr="llma-prompt-compare-versions-button"
                        >
                            Compare versions
                        </LemonButton>
                    )}
                </div>
                {isDiffVisible ? (
                    <PromptDiffView />
                ) : isRenderingMarkdown ? (
                    <>
                        <PromptOutline promptText={promptText} containerRef={markdownContainerRef} className="mt-2" />
                        <div ref={markdownContainerRef}>
                            <LemonMarkdown className="mt-1 rounded border bg-bg-light p-3" generateHeadingIds>
                                {promptText}
                            </LemonMarkdown>
                        </div>
                    </>
                ) : (
                    <pre className="mt-1 max-w-3xl rounded border bg-bg-light p-3 whitespace-pre-wrap">
                        {prompt.prompt}
                    </pre>
                )}
            </div>

            <div className="grid max-w-3xl gap-3 text-sm text-secondary sm:grid-cols-2">
                <div>Published {dayjs(prompt.created_at).format('MMM D, YYYY h:mm A')}</div>
                <div>First version created {dayjs(prompt.first_version_created_at).format('MMM D, YYYY h:mm A')}</div>
            </div>

            {variables.length > 0 && (
                <div className="flex flex-wrap items-center gap-1">
                    <span className="text-xs text-secondary">Variables:</span>
                    {variables.map((variable) => (
                        <LemonTag key={variable} type="highlight" size="small">
                            {variable}
                        </LemonTag>
                    ))}
                </div>
            )}
        </div>
    )
}

export function PublishReviewModal(): JSX.Element | null {
    const { isPublishReviewOpen, prompt, promptForm, nextVersion, isPromptFormSubmitting, versionDescription } =
        useValues(llmPromptLogic)
    const { closePublishReview, submitPromptForm, setVersionDescription } = useActions(llmPromptLogic)

    if (!isPrompt(prompt)) {
        return null
    }

    const publishLabel = nextVersion ? `Publish v${nextVersion}` : 'Publish version'

    return (
        <LemonModal
            isOpen={isPublishReviewOpen}
            onClose={closePublishReview}
            title="Review changes"
            description={`Comparing v${prompt.version} with your edits. Publishing creates ${
                nextVersion ? `v${nextVersion}` : 'a new version'
            } — previous versions stay unchanged.`}
            width={880}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closePublishReview}
                        disabledReason={isPromptFormSubmitting ? 'Publishing…' : undefined}
                        data-attr="llma-prompt-review-back-button"
                    >
                        Back to editing
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitPromptForm}
                        loading={isPromptFormSubmitting}
                        data-attr="llma-prompt-review-publish-button"
                    >
                        {publishLabel}
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-3">
                <div className="overflow-hidden rounded border" data-attr="llma-prompt-publish-review-diff">
                    <Suspense
                        fallback={
                            <div className="space-y-2 p-4">
                                <LemonSkeleton active className="h-4 w-full" />
                                <LemonSkeleton active className="h-4 w-3/4" />
                            </div>
                        }
                    >
                        <MonacoDiffEditor
                            original={prompt.prompt}
                            value={promptForm.prompt}
                            modified={promptForm.prompt}
                            language="markdown"
                            options={{
                                readOnly: true,
                                renderSideBySide: true,
                                minimap: { enabled: false },
                                scrollBeyondLastLine: false,
                                wordWrap: 'on',
                                lineNumbers: 'off',
                                folding: false,
                                hideUnchangedRegions: { enabled: true },
                            }}
                        />
                    </Suspense>
                </div>
                <LemonField.Pure label="What changed?" help="Optional — shown in the version history.">
                    <LemonInput
                        value={versionDescription}
                        onChange={setVersionDescription}
                        placeholder="e.g. Tightened the refusal criteria"
                        maxLength={400}
                        data-attr="llma-prompt-version-description-input"
                    />
                </LemonField.Pure>
            </div>
        </LemonModal>
    )
}

function PromptDiffView(): JSX.Element {
    const { prompt, comparePrompt, comparePromptLoading, compareVersion, compareVersionOptions } =
        useValues(llmPromptLogic)
    const { setCompareVersion } = useActions(llmPromptLogic)

    if (!prompt || !isPrompt(prompt)) {
        return <></>
    }

    const currentVersion = prompt.version
    const original = comparePrompt?.prompt ?? ''
    const modified = prompt.prompt

    return (
        <div className="mt-2 space-y-3" data-attr="llma-prompt-diff-view">
            <div className="flex items-center gap-2">
                <span className="text-sm text-secondary">Comparing</span>
                <LemonSelect
                    size="small"
                    value={compareVersion}
                    options={compareVersionOptions}
                    onChange={(value) => setCompareVersion(value)}
                    data-attr="llma-prompt-diff-version-select"
                />
                <span className="text-sm text-secondary">with v{currentVersion} (current)</span>
            </div>
            {comparePromptLoading ? (
                <div className="space-y-2 rounded border p-4">
                    <LemonSkeleton active className="h-4 w-full" />
                    <LemonSkeleton active className="h-4 w-3/4" />
                    <LemonSkeleton active className="h-4 w-1/2" />
                </div>
            ) : !comparePrompt ? (
                <LemonBanner type="warning">
                    Failed to load version for comparison. Try selecting a different version.
                </LemonBanner>
            ) : (
                <div className="overflow-hidden rounded border">
                    <Suspense
                        fallback={
                            <div className="space-y-2 p-4">
                                <LemonSkeleton active className="h-4 w-full" />
                                <LemonSkeleton active className="h-4 w-3/4" />
                            </div>
                        }
                    >
                        <MonacoDiffEditor
                            original={original}
                            value={modified}
                            modified={modified}
                            language="markdown"
                            options={{
                                readOnly: true,
                                renderSideBySide: true,
                                minimap: { enabled: false },
                                scrollBeyondLastLine: false,
                                wordWrap: 'on',
                                lineNumbers: 'off',
                                folding: false,
                                hideUnchangedRegions: { enabled: true },
                            }}
                        />
                    </Suspense>
                </div>
            )}
        </div>
    )
}

export function PromptRelatedTraces(): JSX.Element {
    const { prompt, relatedTracesQuery, viewAllTracesUrl, analyticsScope } = useValues(llmPromptLogic)
    const { setAnalyticsScope, setRelatedTracesQuery } = useActions(llmPromptLogic)
    const tracesQueryContext = useTracesQueryContext()

    if (!prompt || !isPrompt(prompt)) {
        return <></>
    }

    return (
        <div className="mt-8" data-attr="llma-prompt-related-traces-section">
            <div className="mb-4 flex flex-col gap-3">
                <div className="min-w-0 flex-1">
                    <h3 className="text-lg font-semibold">Related traces</h3>
                    <p className="mt-1 text-sm text-secondary">
                        Send <code className="rounded bg-bg-light px-1">$ai_prompt_name</code> and{' '}
                        <code className="rounded bg-bg-light px-1">$ai_prompt_version</code> with your LLM events for
                        version-specific attribution.
                    </p>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                    <PromptAnalyticsScopeControls
                        analyticsScope={analyticsScope}
                        setAnalyticsScope={setAnalyticsScope}
                    />
                    <LemonButton
                        type="secondary"
                        to={viewAllTracesUrl}
                        size="small"
                        data-attr="llma-prompt-view-all-traces-button"
                    >
                        View all traces
                    </LemonButton>
                </div>
            </div>

            {analyticsScope === PromptAnalyticsScope.Selected && (
                <LemonBanner type="info" className="mb-4">
                    Currently matching <code>$ai_prompt_name="{prompt.name}"</code> and{' '}
                    <code>$ai_prompt_version={prompt.version}</code>. If your events only send the prompt name, switch
                    to all versions.
                </LemonBanner>
            )}

            {relatedTracesQuery && (
                <DataTable
                    query={relatedTracesQuery}
                    setQuery={setRelatedTracesQuery}
                    context={tracesQueryContext}
                    uniqueKey="prompt-related-traces"
                    attachTo={llmPromptLogic}
                />
            )}
        </div>
    )
}

function extractPromptVariables(promptText: string): string[] {
    const matches = promptText.match(/\{\{([^}]+)\}\}/g)
    return matches ? [...new Set(matches.map((match) => match.slice(2, -2).trim()))] : []
}

function buildPythonSnippet(promptName: string, host: string, projectApiKey: string, variables: string[]): string {
    const compileLines = variables.length
        ? `\nsystem_prompt = prompts.compile(result.prompt, {${variables.map((v) => `${JSON.stringify(v)}: '...'`).join(', ')}})`
        : ''
    return `from posthog import Posthog
from posthog.ai.prompts import Prompts

posthog = Posthog(
    '${projectApiKey}',
    host='${host}',
    personal_api_key='<personal_api_key>',  # scope: llm_prompt:read
)
prompts = Prompts(posthog)

result = prompts.get(${JSON.stringify(promptName)}, with_metadata=True, fallback='You are a helpful assistant.')${compileLines}
# result.name / result.version -> send as $ai_prompt_name / $ai_prompt_version on your LLM events`
}

function buildNodeSnippet(promptName: string, host: string, projectApiKey: string, variables: string[]): string {
    const compileLines = variables.length
        ? `\nconst systemPrompt = prompts.compile(result.prompt, {${variables.map((v) => ` ${JSON.stringify(v)}: '...'`).join(',')} })`
        : ''
    return `import { Prompts } from '@posthog/ai'
import { PostHog } from 'posthog-node'

const posthog = new PostHog('${projectApiKey}', {
    host: '${host}',
    personalApiKey: '<personal_api_key>', // scope: llm_prompt:read
})
const prompts = new Prompts({ posthog })

const result = await prompts.get(${JSON.stringify(promptName)}, { fallback: 'You are a helpful assistant.' })${compileLines}
// result.name / result.version -> send as $ai_prompt_name / $ai_prompt_version on your LLM events`
}

export function PromptCodeSnippets({ prompt }: { prompt: LLMPrompt }): JSX.Element {
    const { snippetLanguage } = useValues(llmPromptLogic)
    const { setSnippetLanguage } = useActions(llmPromptLogic)
    const { currentTeam } = useValues(teamLogic)

    const host = window.location.origin
    const projectApiKey = currentTeam?.api_token ?? '<project_api_key>'
    const variables = extractPromptVariables(prompt.prompt)

    return (
        <div className="mb-6" data-attr="llma-prompt-code-snippets">
            <div className="mb-2 flex items-center justify-between gap-2">
                <div>
                    <b>Use this prompt in your code</b>
                    <div className="text-secondary text-sm">
                        Fetch the latest version at runtime — publish new versions without deploying.
                    </div>
                </div>
                <LemonButton
                    type="secondary"
                    size="small"
                    to="https://posthog.com/docs/prompt-management"
                    targetBlank
                    data-attr="llma-prompt-snippet-docs-link"
                >
                    Read the docs
                </LemonButton>
            </div>
            <LemonTabs
                activeKey={snippetLanguage}
                onChange={(key) => setSnippetLanguage(key)}
                size="small"
                tabs={[
                    {
                        key: 'python' as const,
                        label: 'Python',
                        content: (
                            <CodeSnippet language={Language.Python}>
                                {buildPythonSnippet(prompt.name, host, projectApiKey, variables)}
                            </CodeSnippet>
                        ),
                    },
                    {
                        key: 'node' as const,
                        label: 'Node.js',
                        content: (
                            <CodeSnippet language={Language.JavaScript}>
                                {buildNodeSnippet(prompt.name, host, projectApiKey, variables)}
                            </CodeSnippet>
                        ),
                    },
                ]}
            />
        </div>
    )
}

export function PromptUsage({ prompt }: { prompt: LLMPrompt }): JSX.Element {
    const { promptUsageLogQuery, promptUsageTrendQuery, analyticsScope } = useValues(llmPromptLogic)
    const { setAnalyticsScope } = useActions(llmPromptLogic)

    return (
        <div data-attr="llma-prompt-usage-container">
            <PromptCodeSnippets prompt={prompt} />

            <LemonBanner type="info" className="mb-4">
                During the beta period, each prompt fetch is currently charged as a Product analytics event. See the{' '}
                <Link to="https://posthog.com/pricing" target="_blank">
                    pricing page
                </Link>
                .
            </LemonBanner>

            <div className="mb-4 flex flex-col gap-2">
                <div className="min-w-0">
                    <b>Trend</b>
                    <div className="text-secondary">
                        {analyticsScope === PromptAnalyticsScope.Selected
                            ? `Prompt fetches for "${prompt.name}" version ${prompt.version}`
                            : `Prompt fetches for all versions of "${prompt.name}"`}
                    </div>
                </div>

                <PromptAnalyticsScopeControls analyticsScope={analyticsScope} setAnalyticsScope={setAnalyticsScope} />
            </div>
            <Query query={promptUsageTrendQuery} />

            <div className="mb-4 mt-6">
                <b>Log</b>
                <div className="text-secondary">
                    {analyticsScope === PromptAnalyticsScope.Selected
                        ? `Prompt fetch events for "${prompt.name}" version ${prompt.version}`
                        : `Prompt fetch events for all versions of "${prompt.name}"`}
                </div>
            </div>
            <Query query={promptUsageLogQuery} />
        </div>
    )
}

function experimentStatusTag(experiment: ExperimentBasicApi): JSX.Element {
    if (experiment.archived) {
        return <LemonTag type="muted">Archived</LemonTag>
    }
    if (experiment.end_date) {
        return <LemonTag type="completion">Stopped</LemonTag>
    }
    if (experiment.start_date) {
        return <LemonTag type="success">Running</LemonTag>
    }
    return <LemonTag type="default">Draft</LemonTag>
}

function promptMetadata(experiment: ExperimentBasicApi): { templates: string[]; versions: number[] } {
    const params = experiment.parameters as { prompt_metadata?: { templates?: string[]; versions?: number[] } } | null
    const meta = params?.prompt_metadata
    return {
        templates: meta?.templates ?? [],
        versions: meta?.versions ?? [],
    }
}

export function PromptExperiments({ prompt }: { prompt: LLMPrompt }): JSX.Element {
    const { versions } = useValues(llmPromptLogic)
    const { openModal } = useActions(createPromptExperimentModalLogic)
    const { experiments, experimentsLoading } = useValues(promptExperimentsLogic({ promptName: prompt.name }))

    const columns: LemonTableColumns<ExperimentBasicApi> = [
        {
            title: 'Name',
            dataIndex: 'name',
            sticky: true,
            width: '40%',
            render: function Render(_, experiment) {
                return (
                    <LemonTableLink
                        to={urls.experiment(experiment.id)}
                        title={experiment.name}
                        description={experiment.description ?? undefined}
                    />
                )
            },
        },
        {
            title: 'Status',
            render: function Render(_, experiment) {
                return experimentStatusTag(experiment)
            },
        },
        {
            title: 'Versions',
            render: function Render(_, experiment) {
                const meta = promptMetadata(experiment)
                if (meta.versions.length === 0) {
                    return <span className="text-secondary">—</span>
                }
                return (
                    <div className="flex flex-wrap gap-1">
                        {meta.versions.map((v) => (
                            <LemonTag key={v} type="muted">
                                v{v}
                            </LemonTag>
                        ))}
                    </div>
                )
            },
        },
        {
            title: 'Metrics',
            render: function Render(_, experiment) {
                const meta = promptMetadata(experiment)
                if (meta.templates.length === 0) {
                    return <span className="text-secondary">—</span>
                }
                return (
                    <div className="flex flex-wrap gap-1">
                        {meta.templates.map((t) => (
                            <LemonTag key={t} type="default">
                                {t}
                            </LemonTag>
                        ))}
                    </div>
                )
            },
        },
        {
            title: 'Created',
            render: function Render(_, experiment) {
                return <span title={experiment.created_at}>{dayjs(experiment.created_at).fromNow()}</span>
            },
        },
    ]

    return (
        <div data-attr="llma-prompt-experiments-container" className="mt-4 space-y-3">
            <div className="flex items-center justify-between gap-3">
                <div>
                    <h4 className="m-0">Experiments</h4>
                    <p className="text-secondary text-xs m-0">
                        Compare prompt versions side-by-side with a metric template.
                    </p>
                </div>
                <AccessControlAction
                    resourceType={AccessControlResourceType.LlmAnalytics}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={() => openModal(prompt.name, versions)}
                        data-attr="llma-prompt-create-experiment-button"
                    >
                        Create experiment
                    </LemonButton>
                </AccessControlAction>
            </div>
            <LemonTable
                dataSource={experiments}
                columns={columns}
                loading={experimentsLoading}
                emptyState={
                    <div className="p-6 text-center text-secondary">
                        No experiments linked to "{prompt.name}" yet. Click <b>Create experiment</b> to compare two or
                        more versions.
                    </div>
                }
                rowKey="id"
                data-attr="llma-prompt-experiments-table"
            />
            <CreatePromptExperimentModal />
        </div>
    )
}

export function PromptEditForm({
    isHistoricalVersion,
    selectedVersion,
}: {
    isHistoricalVersion: boolean
    selectedVersion: number | null
}): JSX.Element {
    const { promptVariables, isNewPrompt, isRenderingMarkdown, promptForm, publishConflict } = useValues(llmPromptLogic)
    const { toggleMarkdownRendering } = useActions(llmPromptLogic)

    return (
        <div className="mt-4 max-w-3xl space-y-4">
            {publishConflict ? (
                <LemonBanner type="warning" data-attr="llma-prompt-publish-conflict-banner">
                    {publishConflict.latestVersion
                        ? `v${publishConflict.latestVersion} was published while you were editing.`
                        : 'This prompt changed while you were editing.'}{' '}
                    Your edits below are preserved — review them before publishing again.
                </LemonBanner>
            ) : null}

            {isHistoricalVersion && selectedVersion ? (
                <LemonBanner type="info">
                    You are publishing a new latest version from historical version v{selectedVersion}. The original
                    version will remain unchanged.
                </LemonBanner>
            ) : null}

            <LemonField
                name="name"
                label="Name"
                help={
                    isNewPrompt
                        ? `This name is used to fetch the prompt from your code. It must be unique and cannot be changed later. Maximum ${PROMPT_NAME_MAX_LENGTH} characters. Only letters, numbers, hyphens (-), and underscores (_) are allowed.`
                        : 'This name is used to fetch the prompt from your code.'
                }
            >
                <LemonInput
                    placeholder="my-prompt-name"
                    maxLength={PROMPT_NAME_MAX_LENGTH}
                    fullWidth
                    disabledReason={!isNewPrompt ? 'Prompt name cannot be changed after creation' : undefined}
                />
            </LemonField>

            <LemonField
                name="prompt"
                label={
                    <div className="flex items-center gap-2">
                        <span>Prompt</span>
                        <LemonButton
                            size="small"
                            noPadding
                            icon={isRenderingMarkdown ? <IconMarkdownFilled /> : <IconMarkdown />}
                            tooltip="Toggle markdown preview"
                            onClick={(e) => {
                                e.preventDefault()
                                toggleMarkdownRendering()
                            }}
                        />
                    </div>
                }
                help="Use {{variable_name}} to define variables that will be replaced when fetching the prompt from your backend."
            >
                {isRenderingMarkdown ? (
                    <LemonMarkdown className="rounded border bg-bg-light p-3 whitespace-pre-wrap">
                        {promptForm.prompt || '*No prompt content yet*'}
                    </LemonMarkdown>
                ) : (
                    <LemonTextArea
                        placeholder="You are a helpful assistant for {{company_name}}. Help the user with their question about {{topic}}."
                        minRows={10}
                        className="font-mono"
                    />
                )}
            </LemonField>

            {promptVariables.length > 0 && (
                <div className="flex flex-wrap items-center gap-1">
                    <span className="text-xs text-secondary">Variables:</span>
                    {promptVariables.map((variable) => (
                        <LemonTag key={variable} type="highlight" size="small">
                            {variable}
                        </LemonTag>
                    ))}
                </div>
            )}
        </div>
    )
}

export function PromptVersionSidebar({
    promptName,
    prompt,
    versions,
    versionsLoading,
    canLoadMoreVersions,
    loadMoreVersions,
    searchParams,
    readOnly = false,
}: {
    promptName: string
    prompt: LLMPrompt | null
    versions: LLMPromptVersionSummary[]
    versionsLoading: boolean
    canLoadMoreVersions: boolean
    loadMoreVersions: () => void
    searchParams: Record<string, any>
    readOnly?: boolean
}): JSX.Element {
    const { compareVersion } = useValues(llmPromptLogic)
    const { setCompareVersion } = useActions(llmPromptLogic)

    return (
        <aside className="w-full shrink-0 xl:sticky xl:top-4 xl:mt-3 xl:w-80">
            <div className="rounded border bg-surface-primary p-4">
                <div className="mb-3 flex items-center justify-between">
                    <div>
                        <h3 className="font-semibold">Version history</h3>
                        <p className="text-sm text-secondary">
                            {versions.length} of {prompt?.version_count ?? versions.length} loaded
                        </p>
                    </div>
                </div>

                <div className="max-h-[28rem] space-y-2 overflow-y-auto pr-1">
                    {versions.map((versionPrompt) => {
                        const selected = prompt?.id === versionPrompt.id
                        const isCompareTarget = compareVersion === versionPrompt.version
                        const canCompare = !readOnly && prompt?.version !== versionPrompt.version
                        const versionUrl = buildPromptUrl(promptName, searchParams, versionPrompt.version)

                        const cardContent = (
                            <>
                                <div className="mb-1 flex items-center justify-between">
                                    <div className="flex items-center gap-2">
                                        <span className="font-mono text-sm">v{versionPrompt.version}</span>
                                        {versionPrompt.is_latest ? (
                                            <LemonTag type="success" size="small">
                                                Latest
                                            </LemonTag>
                                        ) : null}
                                        {isCompareTarget ? (
                                            <LemonTag type="warning" size="small">
                                                Comparing
                                            </LemonTag>
                                        ) : null}
                                    </div>
                                    {canCompare && (
                                        <LemonButton
                                            size="xsmall"
                                            noPadding
                                            icon={<IconColumns />}
                                            tooltip={
                                                isCompareTarget
                                                    ? 'Stop comparing'
                                                    : `Compare with v${versionPrompt.version}`
                                            }
                                            onClick={(e) => {
                                                e.preventDefault()
                                                e.stopPropagation()
                                                setCompareVersion(isCompareTarget ? null : versionPrompt.version)
                                            }}
                                            data-attr={`llma-prompt-compare-version-${versionPrompt.version}`}
                                        />
                                    )}
                                </div>
                                {versionPrompt.version_description ? (
                                    <div
                                        className="mb-1 line-clamp-2 text-xs"
                                        title={versionPrompt.version_description}
                                    >
                                        {versionPrompt.version_description}
                                    </div>
                                ) : null}
                                <div className="text-xs text-secondary">
                                    {dayjs(versionPrompt.created_at).format('MMM D, YYYY h:mm A')}
                                </div>
                                {versionPrompt.created_by?.email ? (
                                    <div className="mt-1 text-xs text-secondary">{versionPrompt.created_by.email}</div>
                                ) : null}
                            </>
                        )

                        const cardClassName = `block rounded border p-3 no-underline ${
                            selected
                                ? 'border-primary bg-primary-highlight'
                                : isCompareTarget
                                  ? 'border-warning bg-warning-highlight'
                                  : readOnly
                                    ? 'border-primary/10 opacity-75'
                                    : 'border-primary/10 hover:bg-fill-secondary'
                        }`

                        if (readOnly) {
                            return (
                                <div key={versionPrompt.id} className={cardClassName}>
                                    {cardContent}
                                </div>
                            )
                        }

                        return (
                            <Link
                                key={versionPrompt.id}
                                to={versionUrl}
                                className={cardClassName}
                                data-attr={`llma-prompt-version-link-${versionPrompt.version}`}
                            >
                                {cardContent}
                            </Link>
                        )
                    })}
                </div>

                {canLoadMoreVersions ? (
                    <LemonButton
                        className="mt-3 w-full"
                        type="secondary"
                        onClick={loadMoreVersions}
                        loading={versionsLoading}
                        data-attr="llma-prompt-load-more-versions"
                    >
                        Load more versions
                    </LemonButton>
                ) : null}
            </div>
        </aside>
    )
}

export function cleanPromptSearchParams(
    searchParams: Record<string, any>,
    version: number | null
): Record<string, any> {
    const nextSearchParams = { ...searchParams }

    if (version) {
        nextSearchParams.version = version
    } else {
        delete nextSearchParams.version
    }

    delete nextSearchParams.version_id

    delete nextSearchParams.edit
    return nextSearchParams
}

export function buildPromptUrl(promptName: string, searchParams: Record<string, any>, version: number | null): string {
    return combineUrl(urls.aiObservabilityPrompt(promptName), cleanPromptSearchParams(searchParams, version)).url
}

function PromptAnalyticsScopeControls({
    analyticsScope,
    setAnalyticsScope,
}: {
    analyticsScope: PromptAnalyticsScope
    setAnalyticsScope: (analyticsScope: PromptAnalyticsScope) => void
}): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-1 rounded border p-1">
            <LemonButton
                size="xsmall"
                type={analyticsScope === PromptAnalyticsScope.Selected ? 'primary' : 'secondary'}
                onClick={() => setAnalyticsScope(PromptAnalyticsScope.Selected)}
            >
                Selected version
            </LemonButton>
            <LemonButton
                size="xsmall"
                type={analyticsScope === PromptAnalyticsScope.AllVersions ? 'primary' : 'secondary'}
                onClick={() => setAnalyticsScope(PromptAnalyticsScope.AllVersions)}
            >
                All versions
            </LemonButton>
        </div>
    )
}
