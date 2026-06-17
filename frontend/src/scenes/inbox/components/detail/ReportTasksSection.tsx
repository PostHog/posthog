import clsx from 'clsx'
import { useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconChevronRight, IconTerminal } from '@posthog/icons'
import { Link, Spinner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { Task, TaskRunStatus } from 'products/tasks/frontend/types'

import { inboxReportDetailLogic, ReportTaskEntry } from '../../logics/inboxReportDetailLogic'
import { SignalReport, SignalReportTaskRelationship } from '../../types'
import { RightColumnSection } from './DetailSection'

const RELATIONSHIP_LABEL: Record<SignalReportTaskRelationship, string> = {
    research: 'Research',
    implementation: 'Implementation',
    repo_selection: 'Repo selection',
}

const TERMINAL_STATUSES: TaskRunStatus[] = [TaskRunStatus.COMPLETED, TaskRunStatus.FAILED, TaskRunStatus.CANCELLED]

function TaskRunStatusDot({ status }: { status: TaskRunStatus }): JSX.Element {
    const terminal = TERMINAL_STATUSES.includes(status)
    const color =
        status === TaskRunStatus.FAILED || status === TaskRunStatus.CANCELLED
            ? 'bg-danger'
            : terminal
              ? 'bg-success'
              : 'bg-primary'
    return (
        <span
            className={clsx('inline-block size-1.5 shrink-0 rounded-full', color, !terminal && 'animate-pulse')}
            aria-hidden
        />
    )
}

/**
 * Renders the report's linked tasks inline (latest status + relationship) and links out to
 * cloud's existing task detail page. The run-log/session viewer lives there; this is the doorway.
 * Only `implementation` and `research` relationships are shown, implementation-first.
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
                    <TaskRow key={entry.task.id} entry={entry} />
                ))}
            </div>
        </RightColumnSection>
    )
}

function TaskRow({ entry }: { entry: ReportTaskEntry }): JSX.Element {
    const { task, relationship } = entry
    const status = task.latest_run?.status ?? TaskRunStatus.NOT_STARTED
    const runId = task.latest_run?.id
    // Deep-link straight to the task's run logs in cloud's Tasks UI (selecting the latest run),
    // rather than the in-inbox Runs route.
    const taskLogUrl = runId ? combineUrl(urls.taskDetail(task.id), { runId }).url : urls.taskDetail(task.id)
    return (
        <Link
            to={taskLogUrl}
            className="group flex items-center gap-2 rounded px-1.5 py-1 text-left text-xs no-underline transition-colors hover:bg-fill-highlight-50"
        >
            <TaskRunStatusDot status={status} />
            <span className="shrink-0 text-secondary">{RELATIONSHIP_LABEL[relationship]}</span>
            <span className="ml-auto truncate text-tertiary">{getTaskTitle(task)}</span>
            <IconChevronRight className="shrink-0 text-tertiary opacity-0 transition-opacity group-hover:opacity-100" />
        </Link>
    )
}

function getTaskTitle(task: Task): string {
    return task.title || 'Untitled'
}
