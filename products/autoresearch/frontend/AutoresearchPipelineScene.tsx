import { useActions, useValues } from 'kea'

import { IconChevronRight, IconExternal, IconGraph, IconPause, IconPlay, IconRefresh } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCollapse,
    LemonModal,
    LemonSelect,
    LemonSkeleton,
    LemonTab,
    LemonTable,
    LemonTabs,
    LemonTag,
    LemonTextArea,
    Link,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { dayjs } from 'lib/dayjs'
import { LemonMarkdownWithMermaid } from 'lib/lemon-ui/LemonMarkdown/LemonMarkdownWithMermaid'
import { humanizeBytes } from 'lib/utils/numbers'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'

import {
    AutoresearchPipelineLogicProps,
    AutoresearchPipelineTab,
    OnlinePerformanceRow,
    autoresearchPipelineLogic,
    trainingRunProgress,
} from './autoresearchPipelineLogic'
import { DailyVolumeChart } from './DailyVolumeChart'
import {
    AutoresearchIterationStatusEnumApi,
    AutoresearchPipelineApi,
    type AutoresearchRunApi,
    AutoresearchSuggestionApi,
    AutoresearchSuggestionPriorityEnumApi,
    AutoresearchSuggestionStatusEnumApi,
    AutoresearchTrainingRunApi,
    CreateSuggestionPriorityEnumApi,
    IterationTrailApi,
    AutoresearchModelRoleEnumApi,
} from './generated/api.schemas'
import { PipelineStatusTag } from './PipelineStatusTag'
import { ProbabilityHistogram } from './ProbabilityHistogram'

export const scene: SceneExport = {
    component: AutoresearchPipelineScene,
    logic: autoresearchPipelineLogic,
    paramsToProps: ({ params: { id } }): AutoresearchPipelineLogicProps => ({ id }),
}

/** Shared empty-state block: an icon, a headline, supporting copy, and an optional CTA. */
function EmptyTab({
    icon,
    title,
    children,
    cta,
}: {
    icon: JSX.Element
    title: string
    children: React.ReactNode
    cta?: JSX.Element
}): JSX.Element {
    return (
        <div className="flex flex-col items-center text-center gap-2 border border-dashed rounded p-8 text-muted">
            <span className="text-2xl text-secondary">{icon}</span>
            <div className="text-sm font-semibold text-default">{title}</div>
            <div className="text-sm max-w-prose">{children}</div>
            {cta}
        </div>
    )
}

function OverviewTab(): JSX.Element {
    const { pipeline, models } = useValues(autoresearchPipelineLogic)
    if (!pipeline) {
        return <LemonSkeleton className="h-40" />
    }
    const champion = models.find((m) => m.role === AutoresearchModelRoleEnumApi.Champion)
    return (
        <div className="space-y-4">
            <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-muted">Status</span>
                <PipelineStatusTag status={pipeline.status} />
            </div>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                <MetricCard label="Target event" value={pipeline.target_event} />
                <MetricCard label="Prediction horizon" value={`${pipeline.horizon_days ?? '—'}d`} />
                <MetricCard label="Training lookback" value={`${pipeline.training_lookback_days ?? '—'}d`} />
                <MetricCard
                    label="Budget remaining"
                    value={`${pipeline.iteration_budget_remaining} / ${pipeline.iteration_budget ?? '—'}`}
                />
            </div>
            {champion && (
                <div className="border rounded p-4 space-y-4">
                    <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-muted">Champion model</span>
                        {champion.is_preliminary && (
                            <Tooltip title="Promoted on holdout AUC alone. Realized metrics confirm it once prediction horizons elapse.">
                                <LemonTag type="warning">Preliminary</LemonTag>
                            </Tooltip>
                        )}
                    </div>
                    <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
                        <MetricCard
                            label="Holdout AUC"
                            value={champion.holdout_score?.toFixed(3) ?? '—'}
                            tooltip="Offline AUC of the champion model, measured on held-out training data. Higher is better."
                        />
                        <MetricCard
                            label="Realized AUC"
                            value={champion.realized_score?.toFixed(3) ?? '—'}
                            tooltip="AUC of the champion model measured against actual outcomes once predictions matured. Higher is better."
                        />
                        <MetricCard
                            label="Calibration error"
                            value={champion.calibration_error?.toFixed(3) ?? '—'}
                            tooltip="Expected calibration error (ECE): how far predicted probabilities drift from observed rates. Lower is better."
                        />
                    </div>
                    <FeatureImportanceChart explanation={champion.model_explanation} />
                    {champion.agent_description && (
                        <div className="text-sm text-muted italic">"{champion.agent_description}"</div>
                    )}
                </div>
            )}
            <div className="border rounded p-4">
                <DetailRow label="Output person property">
                    <code>{pipeline.output_person_property ?? '—'}</code>
                </DetailRow>
                <DetailRow label="Training population">
                    <span className="font-mono text-xs">{populationSummary(pipeline.training_population)}</span>
                </DetailRow>
                <DetailRow label="Inference population">
                    <span className="font-mono text-xs">{populationSummary(pipeline.inference_population)}</span>
                </DetailRow>
                <DetailRow label="Last scored">
                    {pipeline.last_scored_at ? dayjs(pipeline.last_scored_at).fromNow() : 'Never'}
                </DetailRow>
                <DetailRow label="Created">
                    {dayjs(pipeline.created_at).format('MMM D, YYYY')}
                    {pipeline.created_by?.first_name ? ` by ${pipeline.created_by.first_name}` : ''}
                </DetailRow>
            </div>
            <p className="text-sm text-muted">
                Editing the target, populations, and budget in the UI is coming soon. For now, use the{' '}
                <code>autoresearch</code> API or MCP tools, or recreate the model.
            </p>
        </div>
    )
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex justify-between items-start gap-4 py-2 border-b last:border-0">
            <div className="text-sm font-semibold text-muted">{label}</div>
            <div className="text-sm text-right">{children}</div>
        </div>
    )
}

function populationSummary(population: AutoresearchPipelineApi['training_population']): string {
    if (!population || typeof population !== 'object' || Object.keys(population).length === 0) {
        return 'All users'
    }
    return JSON.stringify(population)
}

function MetricCard({ label, value, tooltip }: { label: string; value: string; tooltip?: string }): JSX.Element {
    const labelElement = (
        <div className={`text-xs font-semibold text-muted uppercase tracking-wide${tooltip ? ' cursor-help' : ''}`}>
            {label}
        </div>
    )
    return (
        <div className="border rounded p-3 space-y-1">
            {tooltip ? <Tooltip title={tooltip}>{labelElement}</Tooltip> : labelElement}
            <div className="text-lg font-bold truncate">{value}</div>
        </div>
    )
}

function languageForArtifact(path: string): Language {
    const lower = path.toLowerCase()
    if (lower.endsWith('.py')) {
        return Language.Python
    }
    if (lower.endsWith('.sql')) {
        return Language.SQL
    }
    if (lower.endsWith('.yml') || lower.endsWith('.yaml')) {
        return Language.YAML
    }
    if (lower.endsWith('.json') || lower.endsWith('.ipynb')) {
        return Language.JSON
    }
    return Language.Text
}

function ArtifactViewerModal(): JSX.Element {
    const { viewedArtifact, viewedArtifactLoading } = useValues(autoresearchPipelineLogic)
    const { closeArtifact } = useActions(autoresearchPipelineLogic)
    return (
        <LemonModal
            isOpen={viewedArtifactLoading || viewedArtifact !== null}
            onClose={closeArtifact}
            title={viewedArtifact?.path ?? 'Artifact'}
            description={
                viewedArtifact
                    ? `${humanizeBytes(viewedArtifact.sizeBytes)} · run ${viewedArtifact.runId.slice(0, 8)}`
                    : undefined
            }
            width={960}
        >
            {viewedArtifactLoading ? (
                <Spinner />
            ) : viewedArtifact?.text != null ? (
                <CodeSnippet language={languageForArtifact(viewedArtifact.path)} wrap maxLinesWithoutExpansion={40}>
                    {viewedArtifact.text}
                </CodeSnippet>
            ) : (
                <div className="text-muted text-sm">
                    Binary file ({viewedArtifact ? humanizeBytes(viewedArtifact.sizeBytes) : ''}). No preview available.
                </div>
            )}
        </LemonModal>
    )
}

const ITERATION_STATUS: Record<
    AutoresearchIterationStatusEnumApi,
    { type: 'success' | 'default' | 'danger'; label: string }
> = {
    kept: { type: 'success', label: 'Kept' },
    discarded: { type: 'default', label: 'Discarded' },
    crashed: { type: 'danger', label: 'Crashed' },
}

// Derived from the field rather than the standalone enum: this pending/running/completed/failed
// set is shared with another product, so the generated enum does not carry an autoresearch name.
type AutoresearchRunStatus = NonNullable<AutoresearchRunApi['status']>

const RUN_STATUS: Record<
    AutoresearchRunStatus,
    { type: 'success' | 'default' | 'danger' | 'highlight'; label: string }
> = {
    pending: { type: 'default', label: 'Pending' },
    running: { type: 'highlight', label: 'Running' },
    completed: { type: 'success', label: 'Completed' },
    failed: { type: 'danger', label: 'Failed' },
}

const MODEL_ROLE: Record<string, { type: 'success' | 'default' | 'highlight'; label: string }> = {
    champion: { type: 'success', label: 'Champion' },
    challenger: { type: 'highlight', label: 'Challenger' },
    archived: { type: 'default', label: 'Archived' },
}

const SUGGESTION_STATUS: Record<
    AutoresearchSuggestionStatusEnumApi,
    { type: 'success' | 'default' | 'danger' | 'highlight'; label: string }
> = {
    queued: { type: 'default', label: 'Queued' },
    picked_up: { type: 'highlight', label: 'Picked up' },
    acted_on: { type: 'success', label: 'Acted on' },
    dismissed: { type: 'danger', label: 'Dismissed' },
}

const SUGGESTION_PRIORITY: Record<AutoresearchSuggestionPriorityEnumApi, string> = {
    consider: 'Consider',
    try_next: 'Try next',
}

/** Render the agent's model_spec (class + hyperparameters) compactly. random_state is noise — drop it. */
function formatModelSpec(spec: unknown): { className: string; params: string } | null {
    if (!spec || typeof spec !== 'object') {
        return null
    }
    const { model_class, model_params } = spec as { model_class?: string; model_params?: Record<string, unknown> }
    const className = (model_class ?? '').split('.').pop() ?? ''
    const params = model_params
        ? Object.entries(model_params)
              .filter(([key]) => key !== 'random_state')
              .map(([key, value]) => `${key}=${value}`)
              .join(', ')
        : ''
    return className || params ? { className, params } : null
}

/** The per-iteration breakdown for one training run: what the agent tried each step and whether it stuck. */
function IterationTrail({ iterations }: { iterations: readonly IterationTrailApi[] }): JSX.Element {
    if (iterations.length === 0) {
        return <div className="text-muted text-sm">No iteration details were recorded for this run.</div>
    }
    const bestHoldout = Math.max(...iterations.map((it) => it.holdout_score ?? -Infinity))
    return (
        <div className="space-y-2">
            {iterations.map((it) => {
                const spec = formatModelSpec(it.model_spec)
                const tag = ITERATION_STATUS[it.status]
                const isBest = it.holdout_score != null && it.holdout_score === bestHoldout
                return (
                    <div key={it.iteration_number} className="border rounded p-2">
                        <div className="flex items-center justify-between gap-2 flex-wrap">
                            <div className="flex items-center gap-2">
                                <span className="text-sm font-semibold">Iteration {it.iteration_number}</span>
                                <LemonTag type={tag.type} size="small">
                                    {tag.label}
                                </LemonTag>
                                {isBest && (
                                    <LemonTag type="completion" size="small">
                                        Best
                                    </LemonTag>
                                )}
                            </div>
                            <div className="text-xs text-muted flex items-center gap-3">
                                <span>
                                    Holdout AUC{' '}
                                    <span className="font-semibold text-default">
                                        {it.holdout_score != null ? it.holdout_score.toFixed(4) : '—'}
                                    </span>
                                </span>
                                {it.train_score != null && <span>Train {it.train_score.toFixed(4)}</span>}
                            </div>
                        </div>
                        {spec && (
                            <div className="text-xs text-muted font-mono mt-1">
                                {spec.className}
                                {spec.params && ` · ${spec.params}`}
                            </div>
                        )}
                        {it.agent_description && (
                            <div className="text-sm text-default mt-1">{it.agent_description}</div>
                        )}
                    </div>
                )
            })}
        </div>
    )
}

/** The agent-authored report.md for a run, rendered as markdown (with mermaid charts). */
function RunReport({ runId }: { runId: string }): JSX.Element | null {
    const { reportByRun, reportByRunLoading } = useValues(autoresearchPipelineLogic)
    const report = reportByRun[runId]
    if (report === undefined) {
        return reportByRunLoading ? <Spinner /> : null
    }
    if (!report) {
        // Loaded, but the agent uploaded no report.md — show nothing; iterations/bundle still render.
        return null
    }
    return (
        <LemonCollapse
            panels={[
                {
                    key: 'report',
                    header: 'Report',
                    content: <LemonMarkdownWithMermaid>{report}</LemonMarkdownWithMermaid>,
                },
            ]}
        />
    )
}

function TrainingRunRow({ run }: { run: AutoresearchTrainingRunApi }): JSX.Element {
    const { expandedRunId, artifactsByRun, artifactsByRunLoading } = useValues(autoresearchPipelineLogic)
    const { toggleRunArtifacts, viewArtifact } = useActions(autoresearchPipelineLogic)
    const isExpanded = expandedRunId === run.id
    const paths = artifactsByRun[run.id]
    const progress = trainingRunProgress(run)
    const startedAt = run.started_at ?? run.created_at
    const duration =
        run.started_at && run.completed_at ? dayjs(run.completed_at).from(dayjs(run.started_at), true) : null
    const runStatus = RUN_STATUS[run.status]
    const progressSummary =
        run.status === 'failed' && progress.iterationCount === 0
            ? 'Failed before any iterations'
            : `${progress.iterationCount} iterations · ${
                  progress.bestHoldoutScore != null
                      ? `best AUC ${progress.bestHoldoutScore.toFixed(3)}`
                      : 'no score yet'
              }`

    return (
        <div className="border rounded">
            <div className="p-3 flex justify-between items-center">
                <div className="flex items-center gap-2">
                    <LemonButton
                        size="small"
                        icon={<IconChevronRight className={`transition-transform ${isExpanded ? 'rotate-90' : ''}`} />}
                        onClick={() => toggleRunArtifacts(run.id)}
                        tooltip={isExpanded ? 'Hide details' : 'Show iterations & bundle'}
                    />
                    <div className="space-y-0.5">
                        <div className="text-sm font-semibold flex items-center gap-1">
                            <Tooltip title={dayjs(startedAt).format('MMM D, YYYY HH:mm')}>
                                <span>Training run · {dayjs(startedAt).fromNow()}</span>
                            </Tooltip>
                            {run.task_url && (
                                <Link
                                    to={run.task_url}
                                    target="_blank"
                                    className="text-muted hover:text-primary"
                                    title="Open sandbox task"
                                >
                                    <IconExternal className="text-sm" />
                                </Link>
                            )}
                            {run.status === 'running' && <Spinner className="ml-2 inline" />}
                        </div>
                        <div className="text-xs text-muted">
                            <span className="font-mono">{run.id.slice(0, 8)}</span> · {progressSummary}
                            {duration ? ` · took ${duration}` : ''}
                        </div>
                    </div>
                </div>
                <LemonTag type={runStatus.type}>{runStatus.label}</LemonTag>
            </div>
            {isExpanded && (
                <div className="border-t p-3 space-y-3">
                    {run.status === 'failed' && run.error && <LemonBanner type="error">{run.error}</LemonBanner>}
                    <RunReport runId={run.id} />
                    <div className="space-y-2">
                        <div className="text-xs font-semibold text-muted uppercase tracking-wide">Iterations</div>
                        <IterationTrail iterations={run.iterations} />
                    </div>
                    {run.summary && (
                        <div className="space-y-1">
                            <div className="text-xs font-semibold text-muted uppercase tracking-wide">
                                What the agent learned
                            </div>
                            {run.summary.distillation && (
                                <div className="text-sm text-default italic">"{run.summary.distillation}"</div>
                            )}
                            {run.summary.recommended_next && (
                                <div className="text-xs text-muted">Next: {run.summary.recommended_next}</div>
                            )}
                        </div>
                    )}
                    <div className="space-y-2">
                        <div className="text-xs font-semibold text-muted uppercase tracking-wide">Artifact bundle</div>
                        {paths === undefined && artifactsByRunLoading ? (
                            <Spinner />
                        ) : paths && paths.length > 0 ? (
                            <div className="flex flex-wrap gap-2">
                                {paths.map((path) => (
                                    <LemonButton
                                        key={path}
                                        type="secondary"
                                        size="small"
                                        onClick={() => viewArtifact({ runId: run.id, path })}
                                    >
                                        {path}
                                    </LemonButton>
                                ))}
                            </div>
                        ) : (
                            <div className="text-muted text-sm">No artifacts uploaded for this run.</div>
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}

function TrainingTab(): JSX.Element {
    const { trainingRuns, trainingRunsLoading, startTrainingResultLoading } = useValues(autoresearchPipelineLogic)
    const { startTraining } = useActions(autoresearchPipelineLogic)

    return (
        <div className="space-y-4">
            <div className="flex items-center gap-2">
                <LemonButton
                    type="primary"
                    onClick={() => void startTraining()}
                    loading={startTrainingResultLoading}
                    disabledReason={startTrainingResultLoading ? 'Starting…' : undefined}
                >
                    Run training
                </LemonButton>
            </div>
            {trainingRunsLoading ? (
                <Spinner />
            ) : trainingRuns.length === 0 ? (
                <EmptyTab icon={<IconRefresh />} title="No training runs yet">
                    Run training to kick off the autoresearch loop. The agent iterates on feature recipes, keeping only
                    the changes that improve holdout AUC.
                </EmptyTab>
            ) : (
                <div className="space-y-2">
                    {trainingRuns.map((run: AutoresearchTrainingRunApi) => (
                        <TrainingRunRow key={run.id} run={run} />
                    ))}
                </div>
            )}
            <ArtifactViewerModal />
        </div>
    )
}

interface FeatureImportance {
    name: string
    direction?: string
    importance?: number
    note?: string
}

/** Pull the typed top-features list + note out of the loosely-typed model_explanation JSON. */
function parseExplanation(explanation: unknown): { features: FeatureImportance[]; note: string | null } {
    if (!explanation || typeof explanation !== 'object') {
        return { features: [], note: null }
    }
    const obj = explanation as { top_features?: unknown; note?: unknown }
    const note = typeof obj.note === 'string' ? obj.note : null
    const raw = Array.isArray(obj.top_features) ? obj.top_features : []
    const features = raw
        .map((f): FeatureImportance | null => {
            if (!f || typeof f !== 'object') {
                return null
            }
            const { name, direction, importance, note: featureNote } = f as Record<string, unknown>
            if (typeof name !== 'string') {
                return null
            }
            return {
                name,
                direction: typeof direction === 'string' ? direction : undefined,
                importance: typeof importance === 'number' ? importance : undefined,
                note: typeof featureNote === 'string' ? featureNote : undefined,
            }
        })
        .filter((f): f is FeatureImportance => f !== null)
    // The agent already lists features strongest-first; only re-rank when it gave numbers.
    if (features.some((f) => f.importance != null)) {
        features.sort((a, b) => (b.importance ?? 0) - (a.importance ?? 0))
    }
    return { features, note }
}

/**
 * A model's top feature drivers: importance bars when the agent supplied numeric
 * importances, otherwise a ranked list with the agent's per-feature notes.
 */
function FeatureImportanceChart({ explanation }: { explanation: unknown }): JSX.Element | null {
    const { features, note } = parseExplanation(explanation)
    if (features.length === 0) {
        return null
    }
    const hasImportances = features.some((f) => f.importance != null)
    const content = (
        <div className="space-y-2">
            <div className="text-xs text-muted">
                <span style={{ color: 'var(--success)' }}>● raises</span>{' '}
                <span style={{ color: 'var(--danger)' }}>● lowers</span> the prediction
                {hasImportances ? ' · bars on a fixed 0-1 importance scale' : ' · strongest first'}
            </div>
            <div className="space-y-1">
                {features.map((f) => {
                    const isNegative = f.direction === 'negative'
                    return (
                        <div key={f.name} className="flex items-center gap-2 text-sm">
                            <div className="w-48 shrink-0 truncate font-mono text-xs" title={f.name}>
                                <span style={{ color: isNegative ? 'var(--danger)' : 'var(--success)' }}>● </span>
                                {f.name}
                            </div>
                            {hasImportances ? (
                                <div
                                    className="flex-1 rounded h-4 overflow-hidden"
                                    style={{ backgroundColor: 'var(--border)' }}
                                >
                                    <Tooltip
                                        title={`${isNegative ? 'Lowers' : 'Raises'} the prediction · importance ${(f.importance ?? 0).toFixed(3)}`}
                                    >
                                        <div
                                            className="h-full rounded"
                                            style={{
                                                width: `${Math.min(100, Math.max(2, (f.importance ?? 0) * 100))}%`,
                                                backgroundColor: isNegative ? 'var(--danger)' : 'var(--success)',
                                            }}
                                        />
                                    </Tooltip>
                                </div>
                            ) : (
                                <Tooltip title={f.note}>
                                    <div className="flex-1 min-w-0 truncate text-xs text-muted">{f.note}</div>
                                </Tooltip>
                            )}
                        </div>
                    )
                })}
            </div>
            {note && <div className="text-xs text-muted italic">{note}</div>}
        </div>
    )
    return (
        <LemonCollapse
            size="small"
            defaultActiveKey="features"
            panels={[{ key: 'features', header: 'Top feature drivers', content }]}
        />
    )
}

/** Links to the person's page. The value is a (person UUID, display name) tuple; the display name falls back to the UUID. */
function PersonCell({ value }: { value: unknown }): JSX.Element {
    const [id, name] = Array.isArray(value) ? value : [value, null]
    const personId = id == null ? '' : String(id)
    if (!personId) {
        return <>—</>
    }
    const display = typeof name === 'string' && name ? name : personId
    return <Link to={urls.personByUUID(personId)}>{display}</Link>
}

function PercentCell({ value }: { value: unknown }): JSX.Element {
    return value == null ? <>—</> : <>{String(value)}%</>
}

/** Top/bottom-N users by predicted probability for a pipeline, grouped by person. */
function ProbabilityUsersTable({
    pipelineId,
    direction,
}: {
    pipelineId: string
    direction: 'DESC' | 'ASC'
}): JSX.Element {
    return (
        <Query
            readOnly
            context={{
                columns: {
                    person: { title: 'Person', render: PersonCell },
                    probability: { title: 'Probability', render: PercentCell },
                    last_scored: { title: 'Last scored' },
                },
            }}
            query={{
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: `
                        WITH latest AS (
                            SELECT max(toDate(timestamp)) AS d
                            FROM events
                            WHERE event = 'autoresearch_prediction'
                              AND properties.$autoresearch_pipeline_id = {pipeline_id}
                        ),
                        scored AS (
                            SELECT
                                coalesce(nullIf(properties.$autoresearch_person_id, ''), distinct_id) AS person_id,
                                round(100 * argMax(toFloat(properties.$autoresearch_p_y), timestamp), 1) AS probability,
                                max(timestamp) AS last_scored
                            FROM events
                            WHERE event = 'autoresearch_prediction'
                              AND properties.$autoresearch_pipeline_id = {pipeline_id}
                              AND toDate(timestamp) = (SELECT d FROM latest)
                            GROUP BY person_id
                        )
                        -- LEFT JOIN persons directly on the person UUID: the implicit person join goes via
                        -- distinct_id, which drops scored people whose prediction events aren't person-mapped.
                        SELECT
                            tuple(s.person_id, coalesce(
                                nullIf(toString(p.properties.email), ''),
                                nullIf(toString(p.properties.name), '')
                            )) AS person,
                            s.probability AS probability,
                            s.last_scored AS last_scored
                        FROM scored s
                        LEFT JOIN persons p ON toString(p.id) = s.person_id
                        ORDER BY probability ${direction}
                        LIMIT 50
                    `,
                    values: { pipeline_id: pipelineId },
                },
            }}
        />
    )
}

function DailyVolumePanel(): JSX.Element {
    const { dailyVolume, dailyVolumeError } = useValues(autoresearchPipelineLogic)

    if (dailyVolumeError) {
        return (
            <p className="text-sm text-muted mb-0">Couldn't load the scoring volume. Refresh the page to try again.</p>
        )
    }
    if (dailyVolume == null) {
        return <LemonSkeleton className="h-44" />
    }
    if (dailyVolume.length === 0) {
        return (
            <p className="text-sm text-muted mb-0">No prediction events found. Score now to emit fresh predictions.</p>
        )
    }
    return <DailyVolumeChart points={dailyVolume} />
}

function ProbabilityDistributionPanel(): JSX.Element {
    const { probabilityHistogram, probabilityDistributionError } = useValues(autoresearchPipelineLogic)

    if (probabilityDistributionError) {
        return (
            <p className="text-sm text-muted mb-0">
                Couldn't load the probability distribution. Refresh the page to try again.
            </p>
        )
    }
    if (probabilityHistogram == null) {
        return <LemonSkeleton className="h-52" />
    }
    if (probabilityHistogram.every((bucket) => bucket.users === 0)) {
        return (
            <p className="text-sm text-muted mb-0">
                No prediction events found for the latest scoring run. Score now to emit fresh predictions.
            </p>
        )
    }
    return <ProbabilityHistogram buckets={probabilityHistogram} />
}

function PredictionsTab(): JSX.Element {
    const { pipeline } = useValues(autoresearchPipelineLogic)
    if (!pipeline) {
        return <LemonSkeleton className="h-40" />
    }

    if (!pipeline.last_scored_at) {
        return (
            <EmptyTab icon={<IconGraph />} title="No predictions yet" cta={<ScoreNowButton />}>
                Once the champion scores your inference population, each user's predicted probability lands on the{' '}
                <code>{pipeline.output_person_property}</code> person property and an{' '}
                <code>autoresearch_prediction</code> event is emitted. Score now to populate this tab.
            </EmptyTab>
        )
    }

    return (
        <div className="space-y-6">
            <p className="text-sm text-muted">
                Each scoring run writes the champion's predicted probability to the{' '}
                <code>{pipeline.output_person_property}</code> person property and emits an{' '}
                <code>autoresearch_prediction</code> event. These views read straight from those events.
            </p>

            <LemonCollapse
                multiple
                defaultActiveKeys={['distribution', 'highest']}
                panels={[
                    {
                        key: 'distribution',
                        header: 'Probability distribution (latest scoring run)',
                        content: <ProbabilityDistributionPanel />,
                    },
                    {
                        key: 'highest',
                        header: 'Highest-probability users (latest scoring run)',
                        content: <ProbabilityUsersTable pipelineId={pipeline.id} direction="DESC" />,
                    },
                    {
                        key: 'lowest',
                        header: 'Lowest-probability users (latest scoring run)',
                        content: <ProbabilityUsersTable pipelineId={pipeline.id} direction="ASC" />,
                    },
                    {
                        key: 'volume',
                        header: 'Daily scoring volume',
                        content: <DailyVolumePanel />,
                    },
                ]}
            />
        </div>
    )
}

function fmt(value: number | null, decimals = 3): string {
    return value != null ? value.toFixed(decimals) : '—'
}

/** Tiny inline sparkline of a metric over prediction dates. No chart deps. */
function MetricSparkline({
    points,
    color = 'var(--success)',
    floor,
    ceil,
}: {
    points: { date: string; value: number }[]
    color?: string
    floor?: number
    ceil?: number
}): JSX.Element | null {
    if (points.length < 2) {
        return null
    }
    const width = 280
    const height = 56
    const pad = 4
    const values = points.map((p) => p.value)
    const min = Math.min(...values, ...(floor != null ? [floor] : []))
    const max = Math.max(...values, ...(ceil != null ? [ceil] : []))
    const span = max - min || 1
    const stepX = (width - pad * 2) / (points.length - 1)
    const coords = points.map((p, i) => {
        const x = pad + i * stepX
        const y = pad + (1 - (p.value - min) / span) * (height - pad * 2)
        return [x, y] as const
    })
    const line = coords.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
    const last = coords[coords.length - 1]
    return (
        <svg width={width} height={height} className="overflow-visible">
            <polyline points={line} fill="none" stroke={color} strokeWidth={2} />
            <circle cx={last[0]} cy={last[1]} r={3} fill={color} />
        </svg>
    )
}

/** A labelled sparkline card showing one realized metric's trend over prediction dates. */
function MetricTrendCard({
    title,
    points,
    color,
    floor,
    ceil,
}: {
    title: string
    points: { date: string; value: number }[]
    color?: string
    floor?: number
    ceil?: number
}): JSX.Element | null {
    if (points.length < 2) {
        return null
    }
    const latest = points[points.length - 1]
    return (
        <div className="border rounded p-3 space-y-1 inline-block">
            <div className="text-xs font-semibold text-muted uppercase tracking-wide">{title}</div>
            <div className="text-lg font-bold">{latest.value.toFixed(3)}</div>
            <MetricSparkline points={points} color={color} floor={floor} ceil={ceil} />
            <div className="text-xs text-muted">
                {dayjs(points[0].date).format('MMM D')} to {dayjs(latest.date).format('MMM D')}
            </div>
        </div>
    )
}

function OnlinePerformanceTab(): JSX.Element {
    const { onlinePerformanceRows, runsLoading } = useValues(autoresearchPipelineLogic)

    if (runsLoading) {
        return <Spinner />
    }

    if (onlinePerformanceRows.length === 0) {
        return (
            <EmptyTab icon={<IconGraph />} title="No realized performance yet">
                Realized metrics appear once prediction horizons elapse. For each prediction date, PostHog joins your{' '}
                <code>autoresearch_prediction</code> events to actual outcomes and computes AUC, Brier score, and lift.
                Trigger evaluation with the <code>autoresearch-validate-online</code> MCP tool or the{' '}
                <code>autoresearch_validate_online</code> management command.
            </EmptyTab>
        )
    }

    // Champion metric trends over time, oldest → newest, for the sparklines.
    const championRows = onlinePerformanceRows
        .filter((r) => r.model_role === 'champion')
        .sort((a, b) => a.prediction_date.localeCompare(b.prediction_date))
    const trend = (pick: (r: OnlinePerformanceRow) => number | null): { date: string; value: number }[] =>
        championRows.filter((r) => pick(r) != null).map((r) => ({ date: r.prediction_date, value: pick(r) as number }))
    const aucTrend = trend((r) => r.realized_auc)
    const brierTrend = trend((r) => r.brier_score)
    const eceTrend = trend((r) => r.calibration_error)

    return (
        <div className="space-y-4">
            <p className="text-sm text-muted">
                Realized performance measured after each prediction horizon elapses. AUC and lift here reflect actual
                user outcomes rather than holdout estimates.
            </p>
            <div className="flex flex-wrap gap-3">
                <MetricTrendCard
                    title="Champion realized AUC"
                    points={aucTrend}
                    color="var(--success)"
                    floor={0.5}
                    ceil={1}
                />
                <MetricTrendCard title="Champion Brier score" points={brierTrend} color="var(--warning)" floor={0} />
                <MetricTrendCard
                    title="Champion calibration error (ECE)"
                    points={eceTrend}
                    color="var(--warning)"
                    floor={0}
                />
            </div>
            <LemonTable
                dataSource={onlinePerformanceRows}
                rowKey={(row) => `${row.run_id}-${row.model_role}`}
                columns={[
                    {
                        title: 'Prediction date',
                        render: (_, row) => <span className="font-mono">{row.prediction_date}</span>,
                    },
                    {
                        title: 'Model',
                        render: (_, row) => (
                            <LemonTag type={MODEL_ROLE[row.model_role]?.type ?? 'default'}>
                                {MODEL_ROLE[row.model_role]?.label ?? row.model_role}
                            </LemonTag>
                        ),
                    },
                    { title: 'Users scored', render: (_, row) => row.n_scored.toLocaleString() },
                    {
                        title: 'Realized AUC',
                        render: (_, row) => <span className="font-semibold">{fmt(row.realized_auc)}</span>,
                    },
                    { title: 'Brier score', render: (_, row) => fmt(row.brier_score) },
                    { title: 'Calibration error', render: (_, row) => fmt(row.calibration_error) },
                    { title: 'Lift at 10%', render: (_, row) => `${fmt(row.lift_at_10, 2)}×` },
                    { title: 'Lift at 20%', render: (_, row) => `${fmt(row.lift_at_20, 2)}×` },
                ]}
            />
            <p className="text-xs text-muted">
                Realized AUC: higher is better. Brier score and calibration error (ECE): lower is better. ECE measures
                how far predicted probabilities drift from observed rates. Lift at k%: ratio of positives in the top k%
                vs a random sample, so 2× means twice as many conversions as random.
            </p>
        </div>
    )
}

function SuggestionForm(): JSX.Element {
    const { suggestionDraft, suggestionPriority, suggestionSubmitResultLoading } = useValues(autoresearchPipelineLogic)
    const { setSuggestionDraft, setSuggestionPriority, submitSuggestion } = useActions(autoresearchPipelineLogic)
    return (
        <div className="border rounded p-3 space-y-2">
            <div className="text-sm font-semibold">Steer the agent</div>
            <LemonTextArea
                value={suggestionDraft}
                onChange={setSuggestionDraft}
                placeholder="e.g. Try a momentum feature: downloads in the last 7 days over the last 30 days."
                minRows={2}
                maxRows={6}
                data-attr="autoresearch-suggestion-input"
            />
            <div className="flex items-center gap-2">
                <LemonSelect
                    size="small"
                    value={suggestionPriority}
                    onChange={(v) => v && setSuggestionPriority(v)}
                    options={[
                        { value: CreateSuggestionPriorityEnumApi.Consider, label: 'Consider (advisory)' },
                        {
                            value: CreateSuggestionPriorityEnumApi.TryNext,
                            label: 'Try next (before autonomous iterations)',
                        },
                    ]}
                />
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={() => submitSuggestion()}
                    loading={suggestionSubmitResultLoading}
                    disabledReason={!suggestionDraft.trim() ? 'Write a suggestion first' : undefined}
                >
                    Send suggestion
                </LemonButton>
            </div>
        </div>
    )
}

function SuggestionsTab(): JSX.Element {
    const { suggestions, suggestionsLoading } = useValues(autoresearchPipelineLogic)
    return (
        <div className="space-y-4">
            <p className="text-sm text-muted">
                Inject a free-text hypothesis into the training loop. The agent reads queued suggestions at the start of
                each iteration batch and decides whether to act on, apply, or dismiss each one.
            </p>
            <SuggestionForm />
            {suggestionsLoading ? (
                <Spinner />
            ) : suggestions.length === 0 ? (
                <div className="text-muted text-sm">No suggestions yet. Send one above to steer the next run.</div>
            ) : (
                <div className="space-y-2">
                    {suggestions.map((s: AutoresearchSuggestionApi) => (
                        <div key={s.id} className="border rounded p-3 space-y-1">
                            <div className="flex items-center gap-2">
                                <LemonTag type={SUGGESTION_STATUS[s.status].type}>
                                    {SUGGESTION_STATUS[s.status].label}
                                </LemonTag>
                                <span className="text-xs text-muted">
                                    {s.priority ? SUGGESTION_PRIORITY[s.priority] : ''}
                                </span>
                                <span className="text-xs text-muted">{dayjs(s.created_at).fromNow()}</span>
                            </div>
                            <div className="text-sm">{s.prompt}</div>
                            {s.agent_response && (
                                <div className="text-sm text-muted italic">Agent: {s.agent_response}</div>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}

/** Score-now action, gated on a champion existing. Reused in the title bar and empty states. */
function ScoreNowButton(): JSX.Element | null {
    const { pipeline, models, scoreResultLoading } = useValues(autoresearchPipelineLogic)
    const { scoreNow } = useActions(autoresearchPipelineLogic)
    const hasChampion = models.some((m) => m.role === AutoresearchModelRoleEnumApi.Champion)
    if (!pipeline || pipeline.status === 'archived') {
        return null
    }
    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconRefresh />}
            onClick={() => scoreNow()}
            loading={scoreResultLoading}
            disabledReason={hasChampion ? undefined : 'Train a champion model first'}
        >
            Score now
        </LemonButton>
    )
}

function PipelineActions(): JSX.Element | null {
    const { pipeline, pipelineLoading } = useValues(autoresearchPipelineLogic)
    const { pausePipeline, resumePipeline } = useActions(autoresearchPipelineLogic)
    if (!pipeline) {
        return null
    }
    return (
        <>
            {pipeline.status === 'paused' ? (
                <LemonButton
                    type="secondary"
                    icon={<IconPlay />}
                    size="small"
                    onClick={() => resumePipeline()}
                    loading={pipelineLoading}
                >
                    Resume
                </LemonButton>
            ) : pipeline.status === 'running' || pipeline.status === 'bootstrapping' ? (
                <LemonButton
                    type="secondary"
                    icon={<IconPause />}
                    size="small"
                    onClick={() => pausePipeline()}
                    loading={pipelineLoading}
                >
                    Pause
                </LemonButton>
            ) : null}
        </>
    )
}

export function AutoresearchPipelineScene(): JSX.Element {
    const { pipeline, pipelineLoading, activeTab } = useValues(autoresearchPipelineLogic)
    const { setActiveTab } = useActions(autoresearchPipelineLogic)

    const tabs: LemonTab<AutoresearchPipelineTab>[] = [
        { key: 'overview', label: 'Overview', content: <OverviewTab /> },
        { key: 'training', label: 'Training', content: <TrainingTab /> },
        { key: 'predictions', label: 'Predictions', content: <PredictionsTab /> },
        { key: 'online_performance', label: 'Online performance', content: <OnlinePerformanceTab /> },
        { key: 'suggestions', label: 'Suggestions', content: <SuggestionsTab /> },
    ]

    const heading = pipeline?.name ?? (pipelineLoading ? '' : 'Model')
    const subheading = pipeline ? `Predict ${pipeline.target_event} within ${pipeline.horizon_days ?? '?'}d` : undefined

    return (
        <SceneContent>
            <SceneTitleSection
                name={heading}
                description={subheading}
                resourceType={{ type: 'experiment' }}
                actions={
                    <>
                        <ScoreNowButton />
                        <PipelineActions />
                    </>
                }
            />

            {pipelineLoading && !pipeline ? (
                <Spinner />
            ) : (
                <LemonTabs
                    activeKey={activeTab}
                    onChange={(key) => setActiveTab(key as AutoresearchPipelineTab)}
                    tabs={tabs}
                    sceneInset
                />
            )}
        </SceneContent>
    )
}
