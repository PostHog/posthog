import { useActions, useValues } from 'kea'

import { IconChevronRight, IconExternal, IconGraph, IconPause, IconPlay, IconRefresh } from '@posthog/icons'
import {
    LemonButton,
    LemonCollapse,
    LemonModal,
    LemonSelect,
    LemonSkeleton,
    LemonTab,
    LemonTabs,
    LemonTag,
    LemonTextArea,
    Link,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { dayjs } from 'lib/dayjs'
import { LemonMarkdownWithMermaid } from 'lib/lemon-ui/LemonMarkdown'
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
} from './autoresearchPipelineLogic'
import {
    AutoresearchIterationStatusEnumApi,
    AutoresearchModelApi,
    AutoresearchPipelineApi,
    AutoresearchPipelineStatusEnumApi,
    AutoresearchSuggestionApi,
    AutoresearchTrainingRunApi,
    CreateSuggestionPriorityEnumApi,
    IterationTrailApi,
    AutoresearchModelRoleEnumApi,
} from './generated/api.schemas'

export const scene: SceneExport = {
    component: AutoresearchPipelineScene,
    logic: autoresearchPipelineLogic,
    paramsToProps: ({ params: { id } }): AutoresearchPipelineLogicProps => ({ id }),
}

function StatusBadge({ status }: { status: AutoresearchPipelineStatusEnumApi }): JSX.Element {
    const typeMap: Record<
        AutoresearchPipelineStatusEnumApi,
        'default' | 'success' | 'warning' | 'highlight' | 'completion'
    > = {
        draft: 'default',
        bootstrapping: 'highlight',
        running: 'success',
        converged: 'completion',
        paused: 'warning',
        archived: 'default',
    }
    const labelMap: Record<AutoresearchPipelineStatusEnumApi, string> = {
        draft: 'Draft',
        bootstrapping: 'Bootstrapping',
        running: 'Running',
        converged: 'Converged',
        paused: 'Paused',
        archived: 'Archived',
    }
    const descriptionMap: Record<AutoresearchPipelineStatusEnumApi, string> = {
        draft: 'Created but never trained. Start a training run to find a first champion.',
        bootstrapping: 'First training run in progress — no champion has been promoted yet.',
        running: 'Live: a champion is promoted and the population is scored on schedule.',
        converged: 'Champion is stable (budget spent or improvement plateaued); still scoring on schedule.',
        paused: 'Scheduled scoring is on hold. Resume to continue scoring.',
        archived: 'Retired. No training or scoring runs.',
    }
    return (
        <Tooltip title={descriptionMap[status]}>
            <LemonTag type={typeMap[status]}>{labelMap[status]}</LemonTag>
        </Tooltip>
    )
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
                <StatusBadge status={pipeline.status} />
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
                <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
                    <MetricCard label="Champion holdout AUC" value={champion.holdout_score?.toFixed(3) ?? '—'} />
                    <MetricCard label="Champion realized AUC" value={champion.realized_score?.toFixed(3) ?? '—'} />
                    <MetricCard label="Calibration error" value={champion.calibration_error?.toFixed(3) ?? '—'} />
                </div>
            )}
            <div className="space-y-1">
                <div className="text-sm font-semibold text-muted">Output person property</div>
                <code className="text-sm">{pipeline.output_person_property ?? '—'}</code>
            </div>
            <div className="space-y-1">
                <div className="text-sm font-semibold text-muted">Last scored</div>
                <div className="text-sm">
                    {pipeline.last_scored_at ? dayjs(pipeline.last_scored_at).fromNow() : 'Never'}
                </div>
            </div>
        </div>
    )
}

function MetricCard({ label, value }: { label: string; value: string }): JSX.Element {
    return (
        <div className="border rounded p-3 space-y-1">
            <div className="text-xs font-semibold text-muted uppercase tracking-wide">{label}</div>
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
                    Binary file — {viewedArtifact ? humanizeBytes(viewedArtifact.sizeBytes) : ''}. Not previewable here.
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
            defaultActiveKey="report"
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
                            Run {run.id.slice(0, 8)}
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
                            {run.iteration_count} iterations ·{' '}
                            {run.best_holdout_score != null
                                ? `best AUC ${run.best_holdout_score.toFixed(3)}`
                                : 'no score yet'}
                        </div>
                    </div>
                </div>
                <LemonTag
                    type={
                        run.status === 'completed'
                            ? 'success'
                            : run.status === 'failed'
                              ? 'danger'
                              : run.status === 'running'
                                ? 'highlight'
                                : 'default'
                    }
                >
                    {run.status}
                </LemonTag>
            </div>
            {isExpanded && (
                <div className="border-t p-3 space-y-3">
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
    importance: number
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
            const { name, direction, importance } = f as Record<string, unknown>
            if (typeof name !== 'string' || typeof importance !== 'number') {
                return null
            }
            return { name, direction: typeof direction === 'string' ? direction : undefined, importance }
        })
        .filter((f): f is FeatureImportance => f !== null)
        .sort((a, b) => b.importance - a.importance)
    return { features, note }
}

/** Horizontal bar chart of a model's top feature importances, coloured by direction. */
function FeatureImportanceChart({ explanation }: { explanation: unknown }): JSX.Element | null {
    const { features, note } = parseExplanation(explanation)
    if (features.length === 0) {
        return null
    }
    const bars = (
        <div className="space-y-2">
            <div className="text-xs text-muted">
                <span style={{ color: 'var(--success)' }}>● raises</span>{' '}
                <span style={{ color: 'var(--danger)' }}>● lowers</span> the prediction · bars on a fixed 0–1 importance
                scale
            </div>
            <div className="space-y-1">
                {features.map((f) => {
                    const isNegative = f.direction === 'negative'
                    return (
                        <div key={f.name} className="flex items-center gap-2 text-sm">
                            <div className="w-48 shrink-0 truncate font-mono text-xs" title={f.name}>
                                {f.name}
                            </div>
                            <div
                                className="flex-1 rounded h-4 overflow-hidden"
                                style={{ backgroundColor: 'var(--border)' }}
                            >
                                <Tooltip
                                    title={`${isNegative ? 'Lowers' : 'Raises'} the prediction · importance ${f.importance.toFixed(3)}`}
                                >
                                    <div
                                        className="h-full rounded"
                                        style={{
                                            width: `${Math.min(100, Math.max(2, f.importance * 100))}%`,
                                            backgroundColor: isNegative ? 'var(--danger)' : 'var(--success)',
                                        }}
                                    />
                                </Tooltip>
                            </div>
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
            panels={[{ key: 'features', header: 'Top feature drivers', content: bars }]}
        />
    )
}

function ModelsTab(): JSX.Element {
    const { models, modelsLoading } = useValues(autoresearchPipelineLogic)
    if (modelsLoading) {
        return <Spinner />
    }
    if (models.length === 0) {
        return (
            <EmptyTab icon={<IconGraph />} title="No models yet">
                Start a training run to create the first champion model. Champions and challengers you accumulate appear
                here with their offline and realized scores.
            </EmptyTab>
        )
    }
    return (
        <div className="space-y-3">
            {models.map((model: AutoresearchModelApi) => (
                <div key={model.id} className="border rounded p-4 space-y-2">
                    <div className="flex items-center gap-2">
                        <LemonTag
                            type={
                                model.role === AutoresearchModelRoleEnumApi.Champion
                                    ? 'success'
                                    : model.role === AutoresearchModelRoleEnumApi.Challenger
                                      ? 'highlight'
                                      : 'default'
                            }
                        >
                            {model.role}
                        </LemonTag>
                        {model.is_preliminary && <LemonTag type="warning">Preliminary</LemonTag>}
                        <span className="text-xs text-muted font-mono">{model.recipe_hash.slice(0, 12)}</span>
                    </div>
                    <div className="grid grid-cols-3 gap-3 text-sm">
                        <div>
                            <div className="text-muted text-xs">Holdout AUC</div>
                            <div className="font-semibold">{model.holdout_score?.toFixed(3) ?? '—'}</div>
                        </div>
                        <div>
                            <div className="text-muted text-xs">Realized AUC</div>
                            <div className="font-semibold">{model.realized_score?.toFixed(3) ?? '—'}</div>
                        </div>
                        <div>
                            <div className="text-muted text-xs">Calibration error</div>
                            <div className="font-semibold">{model.calibration_error?.toFixed(3) ?? '—'}</div>
                        </div>
                    </div>
                    <FeatureImportanceChart explanation={model.model_explanation} />
                    {model.agent_description && (
                        <div className="text-sm text-muted italic">"{model.agent_description}"</div>
                    )}
                </div>
            ))}
        </div>
    )
}

/** Renders a prediction's person_id (a person UUID) as a link to that person's page. */
function PersonLink({ value }: { value: unknown }): JSX.Element {
    const personId = value == null ? '' : String(value)
    if (!personId) {
        return <>—</>
    }
    return <Link to={urls.personByUUID(personId)}>{personId}</Link>
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
            context={{ columns: { person_id: { title: 'Person', render: PersonLink } } }}
            query={{
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: `
                        SELECT
                            coalesce(nullIf(properties.$autoresearch_person_id, ''), distinct_id) AS person_id,
                            round(argMax(toFloat(properties.$autoresearch_p_y), timestamp), 4) AS probability,
                            max(timestamp) AS last_scored
                        FROM events
                        WHERE event = 'autoresearch_prediction'
                          AND properties.$autoresearch_pipeline_id = {pipeline_id}
                        GROUP BY person_id
                        ORDER BY probability ${direction}
                        LIMIT 50
                    `,
                    values: { pipeline_id: pipelineId },
                },
            }}
        />
    )
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

    const values = { pipeline_id: pipeline.id }

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between gap-2">
                <p className="text-sm text-muted">
                    Each scoring run writes the champion's predicted probability to the{' '}
                    <code>{pipeline.output_person_property}</code> person property and emits an{' '}
                    <code>autoresearch_prediction</code> event. These views read straight from those events.
                </p>
                <ScoreNowButton />
            </div>

            <LemonCollapse
                multiple
                defaultActiveKeys={['distribution', 'highest', 'lowest', 'volume']}
                panels={[
                    {
                        key: 'distribution',
                        header: 'Probability distribution (latest scoring run)',
                        content: (
                            <Query
                                readOnly
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
                                            )
                                            SELECT
                                                concat(
                                                    toString(floor(toFloat(properties.$autoresearch_p_y) * 10) / 10),
                                                    '–',
                                                    toString(floor(toFloat(properties.$autoresearch_p_y) * 10) / 10 + 0.1)
                                                ) AS probability_bucket,
                                                count() AS users,
                                                repeat('▇', toInt(round(40 * count() / max(count()) OVER ()))) AS distribution
                                            FROM events
                                            WHERE event = 'autoresearch_prediction'
                                              AND properties.$autoresearch_pipeline_id = {pipeline_id}
                                              AND toDate(timestamp) = (SELECT d FROM latest)
                                            GROUP BY probability_bucket
                                            ORDER BY probability_bucket
                                        `,
                                        values,
                                    },
                                }}
                            />
                        ),
                    },
                    {
                        key: 'highest',
                        header: 'Highest-probability users',
                        content: <ProbabilityUsersTable pipelineId={pipeline.id} direction="DESC" />,
                    },
                    {
                        key: 'lowest',
                        header: 'Lowest-probability users',
                        content: <ProbabilityUsersTable pipelineId={pipeline.id} direction="ASC" />,
                    },
                    {
                        key: 'volume',
                        header: 'Daily scoring volume',
                        content: (
                            <Query
                                readOnly
                                query={{
                                    kind: NodeKind.DataTableNode,
                                    source: {
                                        kind: NodeKind.HogQLQuery,
                                        query: `
                                            SELECT
                                                toDate(timestamp) AS day,
                                                count() AS users_scored,
                                                round(avg(toFloat(properties.$autoresearch_p_y)), 4) AS avg_probability
                                            FROM events
                                            WHERE event = 'autoresearch_prediction'
                                              AND properties.$autoresearch_pipeline_id = {pipeline_id}
                                            GROUP BY day
                                            ORDER BY day DESC
                                            LIMIT 60
                                        `,
                                        values,
                                    },
                                }}
                            />
                        ),
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
    decimals = 3,
    suffix = '',
}: {
    title: string
    points: { date: string; value: number }[]
    color?: string
    floor?: number
    ceil?: number
    decimals?: number
    suffix?: string
}): JSX.Element | null {
    if (points.length < 2) {
        return null
    }
    const latest = points[points.length - 1]
    return (
        <div className="border rounded p-3 space-y-1 inline-block">
            <div className="text-xs font-semibold text-muted uppercase tracking-wide">{title}</div>
            <MetricSparkline points={points} color={color} floor={floor} ceil={ceil} />
            <div className="text-xs text-muted">
                {points[0].date} → {latest.date} · latest {latest.value.toFixed(decimals)}
                {suffix}
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
                user outcomes, not just holdout estimates.
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
            <table className="w-full text-sm border-collapse">
                <thead>
                    <tr className="border-b text-left">
                        <th className="py-2 pr-4 text-xs font-semibold text-muted uppercase tracking-wide">
                            Prediction date
                        </th>
                        <th className="py-2 pr-4 text-xs font-semibold text-muted uppercase tracking-wide">Model</th>
                        <th className="py-2 pr-4 text-xs font-semibold text-muted uppercase tracking-wide">
                            Users scored
                        </th>
                        <th className="py-2 pr-4 text-xs font-semibold text-muted uppercase tracking-wide">
                            Realized AUC
                        </th>
                        <th className="py-2 pr-4 text-xs font-semibold text-muted uppercase tracking-wide">
                            Brier score
                        </th>
                        <th className="py-2 pr-4 text-xs font-semibold text-muted uppercase tracking-wide">
                            Calibration error
                        </th>
                        <th className="py-2 pr-4 text-xs font-semibold text-muted uppercase tracking-wide">
                            Lift at 10%
                        </th>
                        <th className="py-2 pr-4 text-xs font-semibold text-muted uppercase tracking-wide">
                            Lift at 20%
                        </th>
                    </tr>
                </thead>
                <tbody>
                    {onlinePerformanceRows.map((row: OnlinePerformanceRow) => (
                        <tr key={`${row.run_id}-${row.model_role}`} className="border-b last:border-0">
                            <td className="py-2 pr-4 font-mono">{row.prediction_date}</td>
                            <td className="py-2 pr-4">
                                <LemonTag
                                    type={
                                        row.model_role === 'champion'
                                            ? 'success'
                                            : row.model_role === 'challenger'
                                              ? 'highlight'
                                              : 'default'
                                    }
                                >
                                    {row.model_role}
                                </LemonTag>
                            </td>
                            <td className="py-2 pr-4">{row.n_scored.toLocaleString()}</td>
                            <td className="py-2 pr-4 font-semibold">{fmt(row.realized_auc)}</td>
                            <td className="py-2 pr-4">{fmt(row.brier_score)}</td>
                            <td className="py-2 pr-4">{fmt(row.calibration_error)}</td>
                            <td className="py-2 pr-4">{fmt(row.lift_at_10, 2)}×</td>
                            <td className="py-2 pr-4">{fmt(row.lift_at_20, 2)}×</td>
                        </tr>
                    ))}
                </tbody>
            </table>
            <p className="text-xs text-muted">
                Realized AUC: higher is better. Brier score and calibration error (ECE): lower is better — ECE measures
                how far predicted probabilities drift from observed rates. Lift at k%: ratio of positives in the top k%
                vs a random sample — 2× means twice as many conversions as random.
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
                <div className="text-muted text-sm">No suggestions yet — send one above to steer the next run.</div>
            ) : (
                <div className="space-y-2">
                    {suggestions.map((s: AutoresearchSuggestionApi) => (
                        <div key={s.id} className="border rounded p-3 space-y-1">
                            <div className="flex items-center gap-2">
                                <LemonTag
                                    type={
                                        s.status === 'acted_on'
                                            ? 'success'
                                            : s.status === 'dismissed'
                                              ? 'danger'
                                              : s.status === 'picked_up'
                                                ? 'highlight'
                                                : 'default'
                                    }
                                >
                                    {s.status}
                                </LemonTag>
                                <span className="text-xs text-muted">{s.priority}</span>
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

function SettingRow({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
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

function SettingsTab(): JSX.Element {
    const { pipeline } = useValues(autoresearchPipelineLogic)
    if (!pipeline) {
        return <LemonSkeleton className="h-40" />
    }
    return (
        <div className="space-y-4">
            <div className="border rounded p-4">
                <SettingRow label="Target event">
                    <code>{pipeline.target_event}</code>
                </SettingRow>
                <SettingRow label="Prediction horizon">{pipeline.horizon_days ?? '—'} days</SettingRow>
                <SettingRow label="Training lookback">{pipeline.training_lookback_days ?? '—'} days</SettingRow>
                <SettingRow label="Output person property">
                    <code>{pipeline.output_person_property ?? '—'}</code>
                </SettingRow>
                <SettingRow label="Iteration budget">
                    {pipeline.iteration_budget_remaining} / {pipeline.iteration_budget ?? '—'} remaining
                </SettingRow>
                <SettingRow label="Training population">
                    <span className="font-mono text-xs">{populationSummary(pipeline.training_population)}</span>
                </SettingRow>
                <SettingRow label="Inference population">
                    <span className="font-mono text-xs">{populationSummary(pipeline.inference_population)}</span>
                </SettingRow>
                <SettingRow label="Created">
                    {dayjs(pipeline.created_at).format('MMM D, YYYY')} by {pipeline.created_by?.first_name ?? 'unknown'}
                </SettingRow>
            </div>
            <p className="text-sm text-muted">
                Editing the target, populations, schedule, and budget from the UI is coming soon. For now, adjust these
                with the <code>autoresearch</code> API or MCP tools, or recreate the pipeline.
            </p>
        </div>
    )
}

/** Score-now action, gated on a champion existing. Reused in the title bar and empty states. */
function ScoreNowButton({ size = 'small' }: { size?: 'small' | 'medium' }): JSX.Element | null {
    const { pipeline, models, scoreResultLoading } = useValues(autoresearchPipelineLogic)
    const { scoreNow } = useActions(autoresearchPipelineLogic)
    const hasChampion = models.some((m) => m.role === AutoresearchModelRoleEnumApi.Champion)
    if (!pipeline || pipeline.status === 'archived') {
        return null
    }
    return (
        <LemonButton
            type="secondary"
            size={size}
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
        { key: 'models', label: 'Models', content: <ModelsTab /> },
        { key: 'predictions', label: 'Predictions', content: <PredictionsTab /> },
        { key: 'online_performance', label: 'Online performance', content: <OnlinePerformanceTab /> },
        { key: 'suggestions', label: 'Suggestions', content: <SuggestionsTab /> },
        { key: 'settings', label: 'Settings', content: <SettingsTab /> },
    ]

    const heading = pipeline?.name ?? (pipelineLoading ? '' : 'Pipeline')
    const subheading = pipeline ? `Predict ${pipeline.target_event} within ${pipeline.horizon_days ?? '?'}d` : undefined

    return (
        <SceneContent>
            <SceneTitleSection
                name={heading}
                description={subheading}
                resourceType={{ type: 'experiment' }}
                actions={<PipelineActions />}
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
