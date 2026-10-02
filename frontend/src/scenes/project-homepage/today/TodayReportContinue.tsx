import { useActions, useValues } from 'kea'

import { IconClock, IconCopy, IconLogomark, IconPullRequest } from '@posthog/icons'
import { Dot, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { buildReportImplementationPrompt } from 'products/signals/frontend/inbox/components/detail/buildReportImplementationPrompt'
import { IMPLEMENTATION_AGENTS } from 'products/signals/frontend/inbox/components/detail/implementationAgents'
import { captureInboxReportAction } from 'products/signals/frontend/inbox/inboxAnalytics'
import { inboxTaskKickoffLogic } from 'products/signals/frontend/inbox/inboxTaskKickoffLogic'
import type {
    ImplementationSlotClaim,
    ReportTaskEntry,
} from 'products/signals/frontend/inbox/logics/inboxReportDetailLogic'
import { SignalReport } from 'products/signals/frontend/inbox/types'
import { canCreateImplementationPr } from 'products/signals/frontend/inbox/utils/reportActions'
import { primaryReportPullRequest } from 'products/signals/frontend/inbox/utils/reportPullRequests'

import { TodayActionButton } from './TodayActionButton'
import { isSampleReportId } from './todaySampleReports'

const AGENTS = IMPLEMENTATION_AGENTS.filter((agent) => agent.key !== 'posthog-code')
const SAMPLE_REASON = 'Sample reports can’t start work. Turn off sample reports to use a real one.'
const PULL_REQUEST_STATE: Record<string, string> = {
    draft: 'A draft pull request is ready for review.',
    open: 'A pull request is ready for review.',
    merged: 'The pull request is merged.',
}

export function TodayReportContinue({
    report,
    reportUrl,
    reportTaskToOpen,
    implementationSlotClaim,
}: {
    report: SignalReport
    reportUrl: string
    reportTaskToOpen: ReportTaskEntry | null
    implementationSlotClaim: ImplementationSlotClaim | null
}): JSX.Element {
    const { isCreatingPr, isDiscussing, createPrDisabledReason } = useValues(inboxTaskKickoffLogic)
    const { createPrFromReport, openReportTask } = useActions(inboxTaskKickoffLogic)
    const sampleReason = isSampleReportId(report.id) ? SAMPLE_REASON : null
    const pullRequest = primaryReportPullRequest(report)
    const task = reportTaskToOpen?.task
    const run = task?.latest_run

    const runPrompt = (agentKey: string, send: (prompt: string) => void): void => {
        captureInboxReportAction({
            report,
            actionType: 'copy_implementation_prompt',
            surface: 'today',
            extra: { agent: agentKey },
        })
        send(buildReportImplementationPrompt(report, reportUrl))
    }

    const createDisabledReason =
        sampleReason ??
        (!canCreateImplementationPr(report)
            ? 'PostHog starts work only on reports that are ready and need a code change.'
            : null) ??
        createPrDisabledReason ??
        (isDiscussing ? 'Wait for the discussion task to start.' : null) ??
        (implementationSlotClaim ? 'A PostHog task already holds this report.' : null)

    const state = pullRequest.url
        ? (PULL_REQUEST_STATE[pullRequest.merged ? 'merged' : pullRequest.state] ?? null)
        : run
          ? 'A PostHog task is working on this.'
          : null

    const buttonClass = 'w-full min-w-0 justify-center [&>span]:truncate'

    return (
        <section className="@container flex flex-col gap-2" data-attr="today-report-continue">
            <div className="flex items-center justify-between gap-3">
                <Text size="sm" render={<h2 />} className="font-semibold">
                    Continue
                </Text>
                {state && (
                    <Text size="xs" variant="muted" className="flex items-center gap-1.5">
                        <Dot variant="warning" />
                        <span>{state}</span>
                    </Text>
                )}
            </div>
            <div className="grid grid-cols-2 gap-2 @xl:grid-cols-5">
                {pullRequest.url ? (
                    <TodayActionButton
                        variant="outline"
                        className={`${buttonClass} col-span-2 @xl:col-span-1`}
                        render={<LinkPrimitive to={pullRequest.url} target="_blank" />}
                        disabledReason={sampleReason}
                        data-attr="today-report-review-pr"
                    >
                        <IconPullRequest />
                        <span>Review PR</span>
                    </TodayActionButton>
                ) : task && run ? (
                    <TodayActionButton
                        variant="outline"
                        className={`${buttonClass} col-span-2 @xl:col-span-1`}
                        onClick={() => openReportTask(report, task.id, run.id)}
                        data-attr="today-report-open-task"
                    >
                        <IconClock />
                        <span>Open task</span>
                    </TodayActionButton>
                ) : (
                    <TodayActionButton
                        variant="outline"
                        className={`${buttonClass} col-span-2 @xl:col-span-1`}
                        onClick={() => {
                            captureInboxReportAction({ report, actionType: 'create_pr', surface: 'today' })
                            createPrFromReport(report)
                        }}
                        loading={isCreatingPr}
                        disabledReason={createDisabledReason}
                        tooltip="PostHog starts a task and opens a draft pull request"
                        data-attr="today-report-create-pr"
                    >
                        <IconLogomark />
                        <span>PostHog</span>
                    </TodayActionButton>
                )}
                {AGENTS.map((agent) => (
                    <TodayActionButton
                        key={agent.key}
                        variant="outline"
                        className={buttonClass}
                        onClick={() =>
                            runPrompt(agent.key, (prompt) => window.open(agent.buildDeepLink(prompt), '_blank'))
                        }
                        disabledReason={sampleReason}
                        tooltip={`Open the prompt in ${agent.name}`}
                        data-attr={`today-report-open-${agent.key}`}
                    >
                        {agent.icon}
                        <span>{agent.name}</span>
                    </TodayActionButton>
                ))}
                <TodayActionButton
                    variant="outline"
                    className={buttonClass}
                    onClick={() =>
                        runPrompt('clipboard', (prompt) => void copyToClipboard(prompt, 'prompt for your agent'))
                    }
                    disabledReason={sampleReason}
                    tooltip="Copy the prompt for any agent"
                    data-attr="today-report-copy-prompt"
                >
                    <IconCopy />
                    <span>Copy prompt</span>
                </TodayActionButton>
            </div>
        </section>
    )
}
