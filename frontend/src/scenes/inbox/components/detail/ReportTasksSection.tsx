import { useValues } from 'kea'

import { IconChevronRight, IconTerminal } from '@posthog/icons'
import { Link, Spinner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { Task, TaskRunStatus } from 'products/tasks/frontend/types'

import { inboxReportDetailLogic, ReportTaskEntry } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { RightColumnSection } from './DetailSection'
import { RELATIONSHIP_LABEL, TaskRunStatusDot } from './taskRunDisplay'

/**
 * Renders the report's linked tasks inline (latest status + relationship). Each row opens the
 * report's run detail (`AgentRunDetail`), where the task's run log renders inline. Only
 * `implementation` and `research` relationships are shown, implementation-first.
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
                    <TaskRow key={entry.task.id} entry={entry} reportId={report.id} />
                ))}
            </div>
        </RightColumnSection>
    )
}

function TaskRow({ entry, reportId }: { entry: ReportTaskEntry; reportId: string }): JSX.Element {
    const { task, relationship } = entry
    const status = task.latest_run?.status ?? TaskRunStatus.NOT_STARTED
    // Open this report's run detail (the inbox Runs route); `inboxSceneLogic` handles the cross-tab
    // open. The task's run log renders inline there — no need to leave the inbox for the Tasks UI.
    return (
        <Link
            to={urls.inboxReport('runs', reportId)}
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
