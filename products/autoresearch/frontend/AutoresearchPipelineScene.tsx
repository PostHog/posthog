import { useActions, useValues } from 'kea'

import { IconPause, IconPlay } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTab, LemonTabs, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import {
    AutoresearchPipelineLogicProps,
    AutoresearchPipelineTab,
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
                <MetricCard label="Horizon" value={`${pipeline.horizon_days ?? '—'}d`} />
                <MetricCard label="Prediction mode" value={pipeline.prediction_mode ?? '—'} />
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
                        <div key={run.id} className="border rounded p-3 flex justify-between items-center">
                            <div className="space-y-0.5">
                                <div className="text-sm font-semibold">
                                    Run {run.id.slice(0, 8)}
                                    {run.status === 'running' && <Spinner className="ml-2 inline" />}
                                </div>
                                <div className="text-xs text-muted">
                                    {run.iteration_count} iterations ·{' '}
                                    {run.best_holdout_score != null
                                        ? `best AUC ${run.best_holdout_score.toFixed(3)}`
                                        : 'no score yet'}
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
                    ))}
                </div>
            )}
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
        {
            key: 'validation',
            label: 'Validation',
            content: (
                <div className="text-muted text-sm">
                    Realized AUC, Brier score, and lift metrics appear here after prediction horizons have elapsed. Use
                    the <code>autoresearch-validate-online</code> MCP tool to trigger evaluation.
                </div>
            ),
        },
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
    const subheading = pipeline
        ? `Predict ${pipeline.target_event} within ${pipeline.horizon_days ?? '?'}d · ${pipeline.prediction_mode}`
        : undefined

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
