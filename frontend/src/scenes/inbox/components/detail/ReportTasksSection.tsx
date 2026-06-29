import { useActions, useValues } from 'kea'

import { IconChevronDown, IconChevronRight, IconTerminal } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { isTerminalRunStatus } from 'products/posthog_ai/frontend/api/logics'
import { RunViewer } from 'products/posthog_ai/frontend/api/run'
import { TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'

import { inboxReportDetailLogic, ReportTaskEntry } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { RightColumnSection } from './DetailSection'
import { TaskRunStatusDot } from './taskRunDisplay'

/**
 * Renders the report's linked tasks inline (latest status + purpose). Each row expands in place to
 * the task's run transcript via the shared `RunViewer` — live for an in-progress run, static
 * replay once terminal — mirroring the Code experience instead of navigating away to a separate run
 * page. The purpose label is derived from each task's `task_run` artefact; `repo_selection` runs are
 * filtered out.
 */
export function ReportTasksSection({ report }: { report: SignalReport }): JSX.Element | null {
    const { reportTasks, reportTasksLoading } = useValues(inboxReportDetailLogic({ reportId: report.id, report }))

    if (reportTasksLoading && !reportTasks) {
        return (
            <RightColumnSection icon={<IconTerminal />} title="Runs">
                <div className="flex items-center gap-2 text-xs text-tertiary py-1">
                    <Spinner className="size-3" />
                    Loading runs…
                </div>
            </RightColumnSection>
        )
    }

    if (!reportTasks || reportTasks.length === 0) {
        return null
    }

    return (
        <RightColumnSection icon={<IconTerminal />} title="Runs">
            <div className="flex flex-col gap-0.5">
                {reportTasks.map((entry: ReportTaskEntry) => (
                    <TaskRow key={entry.task.id} entry={entry} reportId={report.id} report={report} />
                ))}
            </div>
        </RightColumnSection>
    )
}

function TaskRow({
    entry,
    reportId,
    report,
}: {
    entry: ReportTaskEntry
    reportId: string
    report: SignalReport
}): JSX.Element {
    const { task, purposeLabel } = entry
    const { expandedTaskIds } = useValues(inboxReportDetailLogic({ reportId, report }))
    const { toggleExpandedTask } = useActions(inboxReportDetailLogic({ reportId, report }))

    const status = task.latest_run?.status ?? TaskRunStatus.NOT_STARTED
    const runId = task.latest_run?.id ?? null
    const replayOnly = isTerminalRunStatus(task.latest_run?.status)
    const expanded = expandedTaskIds.includes(task.id)

    return (
        <div>
            <button
                type="button"
                onClick={() => toggleExpandedTask(task.id)}
                className="group flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-xs transition-colors hover:bg-fill-highlight-50"
            >
                {expanded ? (
                    <IconChevronDown className="shrink-0 text-tertiary" />
                ) : (
                    <IconChevronRight className="shrink-0 text-tertiary" />
                )}
                <TaskRunStatusDot status={status} />
                <span className="shrink-0 text-secondary">{purposeLabel}</span>
            </button>

            {expanded ? (
                <div className="mt-1.5 mb-1 ml-1.5">
                    {runId ? (
                        <div className="h-[420px] overflow-y-auto rounded border border-primary bg-surface-primary">
                            <RunViewer
                                taskId={task.id}
                                runId={runId}
                                interaction={replayOnly ? 'read-only' : 'live'}
                                className="px-3 py-2"
                            />
                        </div>
                    ) : (
                        <div className="rounded border border-primary bg-surface-primary px-3 py-2.5 text-xs text-secondary leading-snug">
                            This run hasn’t started yet – its agent log will appear here once it does.
                        </div>
                    )}
                </div>
            ) : null}
        </div>
    )
}
