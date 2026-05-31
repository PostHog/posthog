import { useActions, useValues } from 'kea'

import { IconChevronRight, IconExternal, IconPause, IconPlay } from '@posthog/icons'
import { LemonButton, LemonModal, LemonSkeleton, LemonTab, LemonTabs, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { dayjs } from 'lib/dayjs'
import { humanizeBytes } from 'lib/utils'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import {
    AutoresearchPipelineLogicProps,
    AutoresearchPipelineTab,
    OnlinePerformanceRow,
    autoresearchPipelineLogic,
} from './autoresearchPipelineLogic'
import {
    AutoresearchModelApi,
    AutoresearchPipelineStatusEnumApi,
    AutoresearchRunApi,
    AutoresearchSuggestionApi,
    AutoresearchTrainingRunApi,
    RoleEnumApi,
} from './generated/api.schemas'

export const scene: SceneExport = {
    component: AutoresearchPipelineScene,
    logic: autoresearchPipelineLogic,
    paramsToProps: ({ params: { id } }): AutoresearchPipelineLogicProps => ({ id }),
}

function StatusBadge({ status }: { status: AutoresearchPipelineStatusEnumApi }): JSX.Element {
    const typeMap: Record<
        AutoresearchPipelineStatusEnumApi,
        'default' | 'success' | 'warning' | 'purple' | 'completion'
    > = {
        draft: 'default',
        bootstrapping: 'purple',
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
    return <LemonTag type={typeMap[status]}>{labelMap[status]}</LemonTag>
}

function OverviewTab(): JSX.Element {
    const { pipeline, models } = useValues(autoresearchPipelineLogic)
    if (!pipeline) {
        return <LemonSkeleton className="h-40" />
    }
    const champion = models.find((m) => m.role === RoleEnumApi.Champion)
    return (
        <div className="space-y-4">
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
            width={720}
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
                        tooltip={isExpanded ? 'Hide bundle' : 'Show bundle'}
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
                                ? 'purple'
                                : 'default'
                    }
                >
                    {run.status}
                </LemonTag>
            </div>
            {isExpanded && (
                <div className="border-t p-3 space-y-2">
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
                <div className="text-muted text-sm">No training runs yet.</div>
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

function ModelsTab(): JSX.Element {
    const { models, modelsLoading } = useValues(autoresearchPipelineLogic)
    if (modelsLoading) {
        return <Spinner />
    }
    if (models.length === 0) {
        return <div className="text-muted text-sm">No models yet. Start a training run to create the first model.</div>
    }
    return (
        <div className="space-y-3">
            {models.map((model: AutoresearchModelApi) => (
                <div key={model.id} className="border rounded p-4 space-y-2">
                    <div className="flex items-center gap-2">
                        <LemonTag
                            type={
                                model.role === RoleEnumApi.Champion
                                    ? 'success'
                                    : model.role === RoleEnumApi.Challenger
                                      ? 'purple'
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
                    {model.agent_description && (
                        <div className="text-sm text-muted italic">"{model.agent_description}"</div>
                    )}
                </div>
            ))}
        </div>
    )
}

function fmt(value: number | null, decimals = 3): string {
    return value != null ? value.toFixed(decimals) : '—'
}

function OnlinePerformanceTab(): JSX.Element {
    const { onlinePerformanceRows, runsLoading } = useValues(autoresearchPipelineLogic)

    if (runsLoading) {
        return <Spinner />
    }

    if (onlinePerformanceRows.length === 0) {
        return (
            <div className="space-y-2">
                <div className="text-muted text-sm">
                    Realized performance metrics appear here after prediction horizons elapse. For each prediction date,
                    PostHog joins your <code>autoresearch_prediction</code> events to actual target outcomes and
                    computes AUC, Brier score, and lift.
                </div>
                <div className="text-muted text-sm">
                    To trigger evaluation manually, use the <code>autoresearch-validate-online</code> MCP tool or run
                    the <code>autoresearch_validate_online</code> management command.
                </div>
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <p className="text-sm text-muted">
                Realized performance measured after each prediction horizon elapses. AUC and lift here reflect actual
                user outcomes, not just holdout estimates.
            </p>
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
                                              ? 'purple'
                                              : 'default'
                                    }
                                >
                                    {row.model_role}
                                </LemonTag>
                            </td>
                            <td className="py-2 pr-4">{row.n_scored.toLocaleString()}</td>
                            <td className="py-2 pr-4 font-semibold">{fmt(row.realized_auc)}</td>
                            <td className="py-2 pr-4">{fmt(row.brier_score)}</td>
                            <td className="py-2 pr-4">{fmt(row.lift_at_10, 2)}×</td>
                            <td className="py-2 pr-4">{fmt(row.lift_at_20, 2)}×</td>
                        </tr>
                    ))}
                </tbody>
            </table>
            <p className="text-xs text-muted">
                Realized AUC: higher is better. Brier score: lower is better. Lift at k%: ratio of positives in the top
                k% vs a random sample — 2× means twice as many conversions as random.
            </p>
        </div>
    )
}

function RunsTab(): JSX.Element {
    const { runs, runsLoading } = useValues(autoresearchPipelineLogic)
    if (runsLoading) {
        return <Spinner />
    }
    if (runs.length === 0) {
        return <div className="text-muted text-sm">No inference or validation runs yet.</div>
    }
    return (
        <div className="space-y-2">
            {runs.map((run: AutoresearchRunApi) => (
                <div key={run.id} className="border rounded p-3 flex justify-between items-center">
                    <div className="space-y-0.5">
                        <div className="text-sm font-semibold">
                            {run.run_type} · {run.id.slice(0, 8)}
                        </div>
                        <div className="text-xs text-muted">
                            {run.rows_scored != null ? `${run.rows_scored.toLocaleString()} users` : '—'} ·{' '}
                            {run.started_at ? dayjs(run.started_at).fromNow() : ''}
                        </div>
                        {run.error && <div className="text-xs text-danger">{run.error}</div>}
                    </div>
                    <LemonTag
                        type={
                            run.status === 'completed'
                                ? 'success'
                                : run.status === 'failed'
                                  ? 'danger'
                                  : run.status === 'running'
                                    ? 'purple'
                                    : 'default'
                        }
                    >
                        {run.status}
                    </LemonTag>
                </div>
            ))}
        </div>
    )
}

function SuggestionsTab(): JSX.Element {
    const { suggestions, suggestionsLoading } = useValues(autoresearchPipelineLogic)
    if (suggestionsLoading) {
        return <Spinner />
    }
    if (suggestions.length === 0) {
        return (
            <div className="text-muted text-sm">
                No suggestions yet. Use the <code>autoresearch-suggest</code> MCP tool to inject a hypothesis into the
                training loop.
            </div>
        )
    }
    return (
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
                                        ? 'purple'
                                        : 'default'
                            }
                        >
                            {s.status}
                        </LemonTag>
                        <span className="text-xs text-muted">{s.priority}</span>
                        <span className="text-xs text-muted">{dayjs(s.created_at).fromNow()}</span>
                    </div>
                    <div className="text-sm">{s.prompt}</div>
                    {s.agent_response && <div className="text-xs text-muted italic">Agent: {s.agent_response}</div>}
                </div>
            ))}
        </div>
    )
}

export function AutoresearchPipelineScene(): JSX.Element {
    const { pipeline, pipelineLoading, activeTab } = useValues(autoresearchPipelineLogic)
    const { setActiveTab } = useActions(autoresearchPipelineLogic)

    const tabs: LemonTab<AutoresearchPipelineTab>[] = [
        { key: 'overview', label: 'Overview', content: <OverviewTab /> },
        { key: 'training', label: 'Training', content: <TrainingTab /> },
        { key: 'models', label: 'Models', content: <ModelsTab /> },
        {
            key: 'predictions',
            label: 'Predictions',
            content: (
                <div className="text-muted text-sm">
                    Prediction scores are emitted as <code>autoresearch_prediction</code> events. Query them in{' '}
                    <Link to="/insights">Insights</Link> using the event name.
                </div>
            ),
        },
        { key: 'online_performance', label: 'Online performance', content: <OnlinePerformanceTab /> },
        { key: 'runs', label: 'Runs', content: <RunsTab /> },
        {
            key: 'settings',
            label: 'Settings',
            content: (
                <div className="text-muted text-sm space-y-2">
                    <div>Pipeline settings (target, populations, schedule, budget) coming soon.</div>
                    <div>
                        Use <code>autoresearch-suggest</code> MCP tool or the Suggestions panel (below) to steer the
                        agent.
                    </div>
                    <SuggestionsTab />
                </div>
            ),
        },
    ]

    const heading = pipeline?.name ?? (pipelineLoading ? '' : 'Pipeline')
    const subheading = pipeline ? `Predict ${pipeline.target_event} within ${pipeline.horizon_days ?? '?'}d` : undefined

    return (
        <SceneContent>
            <SceneTitleSection
                name={heading}
                description={subheading}
                resourceType={{ type: 'experiment' }}
                actions={
                    pipeline ? (
                        <>
                            <StatusBadge status={pipeline.status} />
                            {pipeline.status === 'paused' ? (
                                <LemonButton
                                    type="secondary"
                                    icon={<IconPlay />}
                                    size="small"
                                    disabledReason="Resume via API or MCP"
                                >
                                    Resume
                                </LemonButton>
                            ) : pipeline.status === 'running' || pipeline.status === 'bootstrapping' ? (
                                <LemonButton
                                    type="secondary"
                                    icon={<IconPause />}
                                    size="small"
                                    disabledReason="Pause via API or MCP"
                                >
                                    Pause
                                </LemonButton>
                            ) : null}
                        </>
                    ) : null
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
