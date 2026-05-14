import { BindLogic, useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSkeleton, LemonTag, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import type { CatalogTraversalRunDTOApi } from 'products/catalog/frontend/generated/api.schemas'
import { TaskSessionView } from 'products/tasks/frontend/components/TaskSessionView'

import { catalogLogsSceneLogic } from './catalogLogsSceneLogic'
import { CatalogPageTabs } from './CatalogPageTabs'
import { catalogTaskLogsLogic } from './catalogTaskLogsLogic'

export const scene: SceneExport = {
    component: CatalogLogsScene,
    logic: catalogLogsSceneLogic,
    productKey: ProductKey.CATALOG,
}

const STATUS_TYPE: Record<string, 'primary' | 'success' | 'danger' | 'warning' | 'default'> = {
    queued: 'default',
    running: 'warning',
    completed: 'success',
    failed: 'danger',
}

function RunRow({
    run,
    isSelected,
    onClick,
}: {
    run: CatalogTraversalRunDTOApi
    isSelected: boolean
    onClick: () => void
}): JSX.Element {
    const started = run.started_at ? dayjs(run.started_at) : null
    const duration =
        run.started_at && run.completed_at
            ? humanFriendlyDuration(dayjs(run.completed_at).diff(run.started_at, 'second'))
            : null
    return (
        <button
            type="button"
            onClick={onClick}
            className={`w-full text-left px-3 py-2 rounded transition-colors border ${
                isSelected ? 'bg-primary-highlight border-primary' : 'border-transparent hover:bg-bg-light'
            }`}
        >
            <div className="flex items-center justify-between gap-2 mb-1">
                <LemonTag type={STATUS_TYPE[run.status] ?? 'default'} size="small">
                    {run.status}
                </LemonTag>
                {started && <span className="text-xs text-muted">{started.fromNow()}</span>}
            </div>
            <div className="text-xs text-muted">
                {started ? started.format('MMM D, YYYY HH:mm') : '—'}
                {duration && ` · ${duration}`}
            </div>
            <div className="text-xs text-muted mt-1">
                {run.nodes_processed} nodes · {run.descriptions_generated} descs · {run.metrics_proposed} metrics
            </div>
        </button>
    )
}

function RunCounts({ run }: { run: CatalogTraversalRunDTOApi }): JSX.Element {
    const entries: { label: string; value: number }[] = [
        { label: 'Nodes', value: run.nodes_processed },
        { label: 'Columns', value: run.columns_processed },
        { label: 'Relationships', value: run.relationships_proposed },
        { label: 'Descriptions', value: run.descriptions_generated },
        { label: 'Metrics', value: run.metrics_proposed },
    ]
    return (
        <div className="grid grid-cols-5 gap-2 px-4 py-2 border-b">
            {entries.map((e) => (
                <div key={e.label}>
                    <div className="text-xs text-muted">{e.label}</div>
                    <div className="text-sm font-mono">{e.value}</div>
                </div>
            ))}
        </div>
    )
}

function TaskLogsPane({
    projectId,
    taskId,
    taskRunId,
    title,
}: {
    projectId: string
    taskId: string
    taskRunId: string
    title: string
}): JSX.Element {
    const logicProps = { projectId, taskId, taskRunId }
    return (
        <BindLogic logic={catalogTaskLogsLogic} props={logicProps}>
            <TaskLogsPaneInner title={title} />
        </BindLogic>
    )
}

function TaskLogsPaneInner({ title }: { title: string }): JSX.Element {
    const { run, logs, streamEntries, isStreaming, shouldPoll, rawLogsLoading } = useValues(catalogTaskLogsLogic)
    if (rawLogsLoading && streamEntries.length === 0 && !logs) {
        return (
            <div className="flex items-center justify-center py-8">
                <Spinner />
            </div>
        )
    }
    return (
        <div className="flex flex-col" style={{ minHeight: 320 }}>
            <div className="px-4 py-2 border-b text-xs font-semibold text-muted">{title}</div>
            <div className="flex-1 overflow-hidden">
                <TaskSessionView
                    logs={logs}
                    streamEntries={streamEntries}
                    isPolling={shouldPoll && !isStreaming}
                    isStreaming={isStreaming}
                    initialPrompt={null}
                    run={run}
                />
            </div>
        </div>
    )
}

export function CatalogLogsScene(): JSX.Element {
    const { runs, runsLoading, selectedRun, selectedRunId, syncing } = useValues(catalogLogsSceneLogic)
    const { setSelectedRunId, startSync } = useActions(catalogLogsSceneLogic)
    const { currentProjectId } = useValues(teamLogic)
    const projectId = String(currentProjectId)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Semantic layer"
                description="Recent catalog traversal runs and the streaming logs from their agent passes."
                resourceType={{ type: 'data_warehouse' }}
                actions={
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconRefresh />}
                        onClick={startSync}
                        loading={syncing}
                    >
                        Sync
                    </LemonButton>
                }
            />
            <CatalogPageTabs activeTab="logs" />
            <div className="flex gap-3" style={{ minHeight: 480 }}>
                <div className="w-64 flex-shrink-0 border rounded p-2">
                    <div className="text-xs font-semibold text-muted px-2 py-1">Runs</div>
                    {runsLoading && runs.length === 0 ? (
                        <div className="flex flex-col gap-1">
                            <LemonSkeleton className="h-14" />
                            <LemonSkeleton className="h-14" />
                            <LemonSkeleton className="h-14" />
                        </div>
                    ) : runs.length === 0 ? (
                        <div className="px-2 py-4 text-center text-xs text-muted">
                            No traversal runs yet. Trigger one with the Sync button.
                        </div>
                    ) : (
                        <div className="flex flex-col gap-1">
                            {runs.map((run) => (
                                <RunRow
                                    key={run.id}
                                    run={run}
                                    isSelected={selectedRunId ? run.id === selectedRunId : selectedRun?.id === run.id}
                                    onClick={() => setSelectedRunId(run.id)}
                                />
                            ))}
                        </div>
                    )}
                </div>
                <div className="flex-1 border rounded overflow-hidden">
                    {!selectedRun ? (
                        <div className="p-6 text-center text-muted text-sm">Select a run to view its logs.</div>
                    ) : (
                        <div className="flex flex-col h-full">
                            <RunCounts run={selectedRun} />
                            {selectedRun.error && (
                                <div className="px-4 py-2 border-b bg-danger-highlight text-danger text-xs font-mono whitespace-pre-wrap">
                                    {selectedRun.error}
                                </div>
                            )}
                            <div className="px-4 py-2 border-b text-xs text-muted flex gap-4">
                                <span>
                                    Status:{' '}
                                    <LemonTag type={STATUS_TYPE[selectedRun.status] ?? 'default'} size="small">
                                        {selectedRun.status}
                                    </LemonTag>
                                </span>
                                {selectedRun.started_at && (
                                    <span>
                                        Started: <TZLabel time={selectedRun.started_at} showSeconds />
                                    </span>
                                )}
                                {selectedRun.completed_at && (
                                    <span>
                                        Completed: <TZLabel time={selectedRun.completed_at} showSeconds />
                                    </span>
                                )}
                            </div>
                            {selectedRun.description_task_id && selectedRun.description_task_run_id ? (
                                <TaskLogsPane
                                    key={`desc-${selectedRun.id}`}
                                    projectId={projectId}
                                    taskId={selectedRun.description_task_id}
                                    taskRunId={selectedRun.description_task_run_id}
                                    title="Description pass"
                                />
                            ) : (
                                <div className="px-4 py-2 text-xs text-muted">Description pass hasn't started yet.</div>
                            )}
                            <LemonDivider className="my-0" />
                            {selectedRun.metric_task_id && selectedRun.metric_task_run_id ? (
                                <TaskLogsPane
                                    key={`metric-${selectedRun.id}`}
                                    projectId={projectId}
                                    taskId={selectedRun.metric_task_id}
                                    taskRunId={selectedRun.metric_task_run_id}
                                    title="Metric proposal pass"
                                />
                            ) : (
                                <div className="px-4 py-2 text-xs text-muted">
                                    Metric proposal pass hasn't started yet.
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </div>
        </SceneContent>
    )
}
