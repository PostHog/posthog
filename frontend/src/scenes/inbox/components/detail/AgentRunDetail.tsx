import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import {
    IconArrowRight,
    IconCheckCircle,
    IconClock,
    IconDocument,
    IconPullRequest,
    IconSearch,
    IconTerminal,
    IconWarning,
} from '@posthog/icons'
import { LemonButton, Link, Spinner, LemonSelect, LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { SignalNode } from 'scenes/debug/signals/types'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { SANDBOX_BIND_TASK_PARAM } from 'scenes/max/maxLogic'
import { urls } from 'scenes/urls'

import { isTerminalRunStatus } from 'products/posthog_ai/frontend/api/logics'
import { TaskRunStatusDot } from 'products/posthog_ai/frontend/api/primitives'
import { ReadonlyRunSurface } from 'products/posthog_ai/frontend/api/readableRun'
import { Task, TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalCard } from '../../SignalCard'
import { SignalReport, SignalReportStatus } from '../../types'
import { deriveHeadline, parsePrRepoSlug, parsePrUrlParts } from '../../utils/reportPresentation'
import { getSourceProductMeta } from '../badges/sourceProductIcons'
import { DetailSection } from './DetailSection'
import { ReportActivitySection } from './ReportActivitySection'
import { ReportDetailBadges } from './ReportDetail'
import { ReportTasksSection } from './ReportTasksSection'

/**
 * Ready-state run output: a polished outcome card that links to the produced PR or report,
 * mirroring desktop `RunOutputReadyCard`. Status glyph, PR ref / source, headline, and a
 * call-to-action to open the result.
 */
function RunOutputReadyCard({ report }: { report: SignalReport }): JSX.Element {
    const prUrl = report.implementation_pr_url ?? null
    const isPr = !!prUrl
    const prSlug = prUrl ? parsePrRepoSlug(prUrl) : null
    const prNumber = prUrl ? (parsePrUrlParts(prUrl)?.number ?? null) : null
    const sourceMeta = getSourceProductMeta(report.source_products?.[0])
    const headline = report.title || deriveHeadline(report.summary)

    return (
        <Link
            to={urls.inboxReport(isPr ? 'pulls' : 'reports', report.id)}
            className="group flex flex-col gap-2 rounded border border-primary bg-surface-primary px-4 py-3.5 no-underline text-inherit transition-colors duration-150 hover:border-primary hover:bg-surface-secondary"
        >
            <div className="flex items-center gap-2 flex-wrap">
                <span className="flex items-center justify-center size-5 shrink-0 rounded-full bg-success-highlight text-success">
                    {isPr ? <IconPullRequest className="text-xs" /> : <IconCheckCircle className="text-xs" />}
                </span>
                {prSlug && prNumber ? (
                    <span className="font-mono text-[12.5px] text-primary">
                        {prSlug}#{prNumber}
                    </span>
                ) : (
                    <span className="font-medium text-sm text-primary">Report ready</span>
                )}
                <span className="flex-1" />
                {sourceMeta ? (
                    <span className="flex items-center gap-1.5 text-xs text-tertiary">
                        <span className="flex shrink-0 items-center" style={{ color: sourceMeta.color }} aria-hidden>
                            <sourceMeta.Icon className="text-sm" />
                        </span>
                        <span>{sourceMeta.label}</span>
                    </span>
                ) : null}
            </div>
            {headline ? (
                <span className="line-clamp-2 text-[12.5px] text-secondary leading-snug">{headline}</span>
            ) : null}
            <span className="flex items-center gap-1 text-xs text-tertiary">
                {isPr ? 'Open the pull request' : 'Open the report'}
                <IconArrowRight className="transition-transform group-hover:translate-x-0.5" />
            </span>
        </Link>
    )
}

/**
 * Run-output widget: the headline state of an agent run. Ready → outcome card (PR/report);
 * failed → error banner; in-progress / queued → draft summary that fills in live.
 * Mirrors desktop `RunOutputWidget`.
 */
function RunOutputWidget({ report }: { report: SignalReport }): JSX.Element {
    if (report.status === SignalReportStatus.READY || report.implementation_pr_url) {
        return <RunOutputReadyCard report={report} />
    }

    if (report.status === SignalReportStatus.FAILED) {
        return (
            <div className="flex items-center gap-3 rounded border border-danger bg-danger-highlight px-4 py-3.5">
                <span className="flex items-center justify-center size-9 shrink-0 rounded-full bg-danger-highlight text-danger">
                    <IconWarning className="size-4" />
                </span>
                <div className="flex flex-col gap-0.5 min-w-0 flex-1">
                    <span className="font-medium text-sm text-primary">Run failed</span>
                    <span className="text-xs text-secondary leading-snug">
                        Research couldn't complete – check the linked run below for the error. The agent may retry
                        automatically.
                    </span>
                </div>
            </div>
        )
    }

    return (
        <DetailSection icon={<IconDocument />} title="Draft summary">
            {report.summary ? (
                <LemonMarkdown className="text-sm text-secondary leading-normal" disableImages>
                    {report.summary}
                </LemonMarkdown>
            ) : (
                <p className="text-sm text-tertiary m-0">
                    {report.status === SignalReportStatus.IN_PROGRESS
                        ? 'The agent is investigating – partial findings will appear here as they land.'
                        : 'Queued for research.'}
                </p>
            )}
        </DetailSection>
    )
}

/**
 * Compact run-state strip: live/finished status, the produced branch (when a PR exists), and run
 * timing. Mirrors desktop's run-state header line (status · branch · timing); the agent transcript
 * itself renders inline below in `TaskLogSection`.
 */
function RunStateStrip({ report }: { report: SignalReport }): JSX.Element {
    const isLive =
        report.status === SignalReportStatus.IN_PROGRESS || report.status === SignalReportStatus.PENDING_INPUT
    const isFailed = report.status === SignalReportStatus.FAILED
    const prSlug = report.implementation_pr_url ? parsePrRepoSlug(report.implementation_pr_url) : null
    const timestamp = report.updated_at ?? report.created_at

    return (
        <div className="flex items-center gap-x-3 gap-y-1 flex-wrap text-xs text-tertiary">
            <span className="flex items-center gap-1.5 font-medium text-secondary">
                <span
                    className={
                        'inline-block size-1.5 shrink-0 rounded-full ' +
                        (isFailed ? 'bg-danger' : isLive ? 'bg-primary animate-pulse' : 'bg-success')
                    }
                    aria-hidden
                />
                {isFailed ? 'Failed' : isLive ? 'Running' : 'Finished'}
            </span>
            {prSlug ? (
                <span className="flex items-center gap-1 font-mono">
                    <IconPullRequest className="text-sm" />
                    {prSlug}
                </span>
            ) : null}
            <span className="flex items-center gap-1">
                <IconClock className="text-sm" />
                <span>{isLive ? 'Started' : 'Updated'}</span>
                <TZLabel time={timestamp} />
            </span>
        </div>
    )
}

/** The selected run's agent transcript, or a loading / empty placeholder. */
function TaskLogBody({
    loading,
    task,
    runId,
    replayOnly,
}: {
    loading: boolean
    task: Task | null
    runId: string | null
    replayOnly: boolean
}): JSX.Element {
    if (loading) {
        return (
            <div className="flex flex-col gap-2">
                <LemonSkeleton className="h-4 w-36" />
                <LemonSkeleton className="h-28 w-full" />
            </div>
        )
    }

    if (task && runId) {
        return (
            <div className="h-[calc(100dvh-22rem)] min-h-[420px] w-full overflow-hidden rounded border border-primary bg-surface-primary">
                {/* In-progress runs stream live; terminal runs show the static replay. */}
                <ReadonlyRunSurface
                    taskId={task.id}
                    runId={runId}
                    interaction={replayOnly ? 'read-only' : 'live'}
                    threadRowClassName="px-3"
                    threadListClassName="py-3"
                />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2 rounded border border-primary bg-surface-primary px-4 py-3.5">
            <span className="font-medium text-sm text-primary">
                {task ? 'Run hasn’t started yet' : 'Waiting for the linked task'}
            </span>
            <span className="max-w-2xl text-xs text-secondary leading-snug">
                {task
                    ? 'This task is queued – its agent log will appear here once the run starts.'
                    : 'Once the agent links this run to a task, its agent log appears here.'}
            </span>
        </div>
    )
}

/**
 * "Open task": continues the selected task in a new PostHog AI chat bound to it — the chat's first
 * message creates a conversation linked to this task and resumes its run interactively. A plain click
 * opens PostHog AI in the side panel (staying in the inbox); cmd/ctrl/middle-click follows the href to
 * open a new tab, carrying the bind via the `bind_task` URL param. Gated to a terminal run — the live
 * Task log already covers an in-progress run, and taking over a running automation run is out of scope.
 */
export function OpenTaskButton({ taskId, runStatus }: { taskId: string; runStatus?: TaskRunStatus }): JSX.Element {
    const { openSidePanelMaxWithTaskBind } = useActions(maxGlobalLogic)
    const isTerminal = isTerminalRunStatus(runStatus)

    return (
        <LemonButton
            size="small"
            type="secondary"
            to={combineUrl(urls.ai(), { [SANDBOX_BIND_TASK_PARAM]: taskId }).url}
            onClick={(e) => {
                // Plain left-click: open the side panel in place rather than navigating to /ai.
                // Link lets a modified click (cmd/ctrl/middle) through to the href for a new tab.
                e.preventDefault()
                openSidePanelMaxWithTaskBind(taskId)
            }}
            disabledReason={isTerminal ? undefined : 'Available once the run finishes'}
            tooltip="Continue this task in a new PostHog AI chat"
        >
            Open task
        </LemonButton>
    )
}

/**
 * Inline "Task log": the selected linked task's agent transcript, rendered with the shared
 * `ReadonlyRunSurface` — live for an in-progress run, static replay once terminal. A `LemonSelect`
 * switches between linked tasks (research / implementation) when there's more than one; "Open task"
 * continues the task in a new PostHog AI chat. Mirrors desktop `AgentRunDetail`'s Task-log section.
 */
function TaskLogSection({ report }: { report: SignalReport }): JSX.Element {
    const { reportTasks, reportTasksLoading, selectedTask } = useValues(
        inboxReportDetailLogic({ reportId: report.id, report })
    )
    const { setSelectedTaskId } = useActions(inboxReportDetailLogic({ reportId: report.id, report }))

    const task = selectedTask?.task ?? null
    const runId = task?.latest_run?.id ?? null
    const runStatus = task?.latest_run?.status
    const replayOnly = isTerminalRunStatus(runStatus)

    const rightSlot = task ? (
        <div className="flex items-center gap-2">
            {reportTasks && reportTasks.length > 1 && (
                <LemonSelect
                    size="small"
                    value={task.id}
                    onChange={(id) => setSelectedTaskId(id)}
                    options={reportTasks.map((entry) => ({
                        value: entry.task.id,
                        label: (
                            <span className="flex items-center gap-1.5">
                                <TaskRunStatusDot status={entry.task.latest_run?.status ?? TaskRunStatus.NOT_STARTED} />
                                {entry.purposeLabel}
                            </span>
                        ),
                    }))}
                />
            )}
            <OpenTaskButton taskId={task.id} runStatus={runStatus} />
        </div>
    ) : null

    return (
        <DetailSection icon={<IconTerminal />} title="Task log" rightSlot={rightSlot}>
            <TaskLogBody
                loading={reportTasksLoading && !reportTasks}
                task={task}
                runId={runId}
                replayOnly={replayOnly}
            />
        </DetailSection>
    )
}

/**
 * Agent run detail body. Shows the run state strip + output state, the linked run's agent transcript
 * inline (`TaskLogSection`, via the shared `ReadonlyRunSurface`), and contributing evidence.
 * Mirrors desktop `AgentRunDetail`.
 */
export function AgentRunDetail({ report }: { report: SignalReport }): JSX.Element {
    const { reportSignals, reportSignalsLoading, isReResearch, priorityExplanation, actionabilityExplanation } =
        useValues(inboxReportDetailLogic({ reportId: report.id, report }))
    const signals = reportSignals ?? []
    const evidenceCount = reportSignals !== null ? signals.length : report.signal_count

    return (
        <div className="@container w-full max-w-[calc(160ch+5rem)] mx-auto px-6 py-5 text-sm">
            <div className="flex items-center gap-2 flex-wrap mb-4">
                <ReportDetailBadges
                    report={report}
                    priorityExplanation={priorityExplanation}
                    actionabilityExplanation={actionabilityExplanation}
                />
                {isReResearch && (
                    <Tooltip title="A prior research run on this report already completed – this is a re-attempt.">
                        <LemonTag size="small" type="warning" className="cursor-help select-none">
                            Re-research
                        </LemonTag>
                    </Tooltip>
                )}
            </div>

            <div className="grid grid-cols-1 @4xl:grid-cols-[minmax(0,80ch)_minmax(0,1fr)] gap-5">
                <div className="flex flex-col min-w-0 gap-5">
                    <RunStateStrip report={report} />
                    <RunOutputWidget report={report} />
                    <TaskLogSection report={report} />
                </div>

                <div className="flex flex-col min-w-0 gap-5">
                    {evidenceCount > 0 && (
                        <DetailSection
                            icon={<IconSearch />}
                            title="Evidence so far"
                            rightSlot={
                                <span className="text-[0.6875rem] text-tertiary tabular-nums">
                                    {evidenceCount} finding{evidenceCount === 1 ? '' : 's'}
                                </span>
                            }
                        >
                            {reportSignalsLoading && reportSignals === null ? (
                                <div className="flex items-center gap-2 text-xs text-tertiary py-1">
                                    <Spinner className="size-3" />
                                    Loading findings…
                                </div>
                            ) : (
                                <div className="flex flex-col gap-3">
                                    {signals.map((signal: SignalNode) => (
                                        <SignalCard key={signal.signal_id} signal={signal} />
                                    ))}
                                </div>
                            )}
                        </DetailSection>
                    )}
                    <ReportTasksSection report={report} />
                    <ReportActivitySection report={report} />
                </div>
            </div>
        </div>
    )
}
