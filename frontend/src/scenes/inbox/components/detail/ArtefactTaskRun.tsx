import { useEffect, useState } from 'react'

import { IconChevronDown, IconChevronRight, IconExternal } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import api from 'lib/api'
import { identifierToHuman } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { isTerminalRunStatus } from 'products/posthog_ai/frontend/api/logics'
import { ReadonlyRunSurface } from 'products/posthog_ai/frontend/api/readableRun'
import { Task, TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'

import { isCustomAgentTaskRun, taskRunTypeLabel, TaskRunArtefactContent } from './artefactTypes'
import { TaskRunStatusDot } from './taskRunDisplay'

/**
 * A `task_run` artefact: the linked task badged from its `(product, type)` (signals-pipeline runs
 * show Research / Implementation / Repo selection; custom agents show their humanized product +
 * type), expanding to the task's run transcript via the shared `ReadonlyRunSurface`. Mirrors desktop
 * `ArtefactTaskRun` (which embeds `TaskLogsPanel`). The task is resolved lazily and the row is
 * disabled until it loads.
 */
export function ArtefactTaskRun({
    content,
    knownTask,
}: {
    content: TaskRunArtefactContent
    /** The resolved task, when the detail logic already fetched it (research/implementation runs) —
     * lets the row skip a redundant `GET /tasks/{id}`. Falls back to a lazy fetch otherwise. */
    knownTask?: Task | null
}): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const [fetchedTask, setFetchedTask] = useState<Task | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(false)
    const task = knownTask ?? fetchedTask

    useEffect(() => {
        // The detail logic already resolved this task — no need to fetch it again.
        if (knownTask || !content.task_id) {
            return
        }
        setLoading(true)
        let cancelled = false
        api.tasks
            .get(content.task_id)
            .then((result) => {
                if (!cancelled) {
                    setFetchedTask(result)
                }
            })
            .catch(() => {
                if (!cancelled) {
                    setError(true)
                }
            })
            .finally(() => {
                if (!cancelled) {
                    setLoading(false)
                }
            })
        return () => {
            cancelled = true
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [content.task_id, knownTask])

    const status = task?.latest_run?.status ?? TaskRunStatus.NOT_STARTED
    // Prefer the run the artefact actually recorded; a task that's been re-run has a newer
    // `latest_run`, so falling back to it would show the wrong transcript. A specific older run has
    // an unknown status, so force the static replay rather than opening an SSE stream for it.
    const isHistoricalRun = !!content.run_id && content.run_id !== task?.latest_run?.id
    const runId = content.run_id ?? task?.latest_run?.id ?? null
    const replayOnly = isHistoricalRun || isTerminalRunStatus(task?.latest_run?.status)
    const isCustom = isCustomAgentTaskRun(content)

    if (error) {
        return <span className="text-[11px] text-danger">Couldn't load this task.</span>
    }

    return (
        <div>
            <div className="flex items-center gap-1">
                <button
                    type="button"
                    disabled={!task}
                    onClick={() => setExpanded((v) => !v)}
                    className="flex min-w-0 flex-1 items-center gap-2 rounded px-1 py-0.5 text-left text-xs transition-colors enabled:hover:bg-fill-highlight-50 disabled:cursor-default"
                >
                    {expanded ? (
                        <IconChevronDown className="shrink-0 text-tertiary" />
                    ) : (
                        <IconChevronRight className="shrink-0 text-tertiary" />
                    )}
                    <TaskRunStatusDot status={status} />
                    <LemonTag size="small" type="muted">
                        {taskRunTypeLabel(content)}
                    </LemonTag>
                    {isCustom ? (
                        <LemonTag size="small" type="completion">
                            {identifierToHuman(content.product)}
                        </LemonTag>
                    ) : null}
                    <span className="truncate text-secondary">
                        {loading ? 'Loading task…' : (task?.title ?? content.task_id)}
                    </span>
                </button>
                {task ? (
                    <LemonButton
                        size="xsmall"
                        icon={<IconExternal />}
                        to={urls.taskDetail(task.id)}
                        tooltip="Open in task view to resume the conversation"
                        className="shrink-0"
                    />
                ) : null}
            </div>

            {expanded && task && runId ? (
                <div className="mt-2 h-[420px] overflow-hidden rounded border border-primary bg-surface-primary">
                    <ReadonlyRunSurface
                        taskId={task.id}
                        runId={runId}
                        interaction={replayOnly ? 'read-only' : 'live'}
                        threadRowClassName="px-3"
                        threadListClassName="py-3"
                    />
                </div>
            ) : null}
        </div>
    )
}
