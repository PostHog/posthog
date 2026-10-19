import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconClock, IconPullRequest, IconSparkles } from '@posthog/icons'
import { Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { Composer } from 'products/posthog_ai/frontend/api/composer'
import { inboxTaskKickoffLogic } from 'products/signals/frontend/inbox/inboxTaskKickoffLogic'
import type {
    ImplementationSlotClaim,
    ReportTaskEntry,
} from 'products/signals/frontend/inbox/logics/inboxReportDetailLogic'
import { SignalReport } from 'products/signals/frontend/inbox/types'

import { TodayActionButton } from './TodayActionButton'
import { TodayImplementMenu } from './TodayImplementMenu'
import { TodayPrimaryAction, startDisabledReason, todayNextStep } from './todayNextStep'
import { todayReportLogic } from './todayReportLogic'
import { SAMPLE_REPORT_REASON } from './todaySampleReports'

function PrimaryAction({
    primary,
    report,
    reportUrl,
    isSample,
    startReason,
}: {
    primary: TodayPrimaryAction
    report: SignalReport
    reportUrl: string
    isSample: boolean
    startReason: string | null
}): JSX.Element {
    const { openReportTask } = useActions(inboxTaskKickoffLogic)
    if (primary.kind === 'review') {
        return (
            <TodayActionButton
                variant="primary"
                className="me-1"
                nativeButton={false}
                render={<LinkPrimitive to={primary.url} target="_blank" />}
                disabledReason={isSample ? SAMPLE_REPORT_REASON : null}
                data-attr="today-report-review-pr"
            >
                <IconPullRequest />
                <span>{primary.label}</span>
            </TodayActionButton>
        )
    }
    if (primary.kind === 'open_task') {
        return (
            <TodayActionButton
                variant="primary"
                className="me-1"
                onClick={() => openReportTask(report, primary.taskId, primary.runId)}
                data-attr="today-report-open-task"
            >
                <IconClock />
                <span>{primary.label}</span>
            </TodayActionButton>
        )
    }
    return (
        <TodayImplementMenu
            report={report}
            reportUrl={reportUrl}
            disabledReason={isSample ? SAMPLE_REPORT_REASON : null}
            postHogDisabledReason={startReason}
        />
    )
}

export function TodayReportNextStep({
    report,
    reportTaskToOpen,
    slotClaim,
}: {
    report: SignalReport
    reportTaskToOpen: ReportTaskEntry | null
    slotClaim: ImplementationSlotClaim | null
}): JSX.Element | null {
    const { createPrDisabledReason, aiConsentDisabledReason } = useValues(inboxTaskKickoffLogic)
    const logic = todayReportLogic({ reportId: report.id })
    const { reportState, reportUrl, isSample, page, askingAi, composerOpen, draft } = useValues(logic)
    const { askAboutReport, openComposer, setDraft } = useActions(logic)
    const textAreaRef = useRef<HTMLTextAreaElement>(null)
    const task = reportTaskToOpen?.task
    const { primary, note, taskPickedUp } = todayNextStep(report, {
        namedPullRequest: page?.named_pull_request ?? null,
        solutionNamesPullRequest: page?.solution_names_pull_request ?? false,
        slotClaimed: slotClaim !== null,
        runningTask: task?.latest_run ? { taskId: task.id, runId: task.latest_run.id } : null,
    })

    if (reportState !== 'open') {
        return null
    }

    const askDisabledReason = isSample ? SAMPLE_REPORT_REASON : null

    const focusComposer = (): void => {
        openComposer()
        requestAnimationFrame(() => {
            const textArea = textAreaRef.current
            textArea?.focus({ preventScroll: true })
            textArea?.setSelectionRange(textArea.value.length, textArea.value.length)
        })
    }

    return (
        <div className="flex flex-col gap-2" data-attr="today-report-continue">
            <div className="flex flex-wrap items-center gap-1">
                {primary && (
                    <PrimaryAction
                        primary={primary}
                        report={report}
                        reportUrl={reportUrl}
                        isSample={isSample}
                        startReason={startDisabledReason(report, taskPickedUp, {
                            createPrDisabledReason,
                            aiConsentDisabledReason,
                        })}
                    />
                )}
                <TodayActionButton
                    className={primary ? undefined : '-ms-2'}
                    onClick={focusComposer}
                    disabledReason={askDisabledReason}
                    data-attr="today-report-ask"
                >
                    <IconSparkles />
                    Ask about it
                </TodayActionButton>
            </div>
            {note && (
                <Text size="xs" render={<p />} className="flex items-center gap-1.5">
                    <IconClock className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                    <span>{note}</span>
                </Text>
            )}
            {composerOpen && (
                <Composer.Root
                    value={draft}
                    onChange={setDraft}
                    onSubmit={() => askAboutReport(draft.trim())}
                    textAreaRef={textAreaRef}
                    loading={askingAi}
                    disabled={askingAi}
                >
                    <Composer.Frame>
                        <Composer.Field>
                            <Composer.Placeholder>Ask PostHog AI about this report</Composer.Placeholder>
                            <Composer.Textarea
                                maxRows={6}
                                className="[mask-image:linear-gradient(to_bottom,black_calc(100%-1rem),transparent)]"
                                data-attr="today-report-prompt-input"
                            />
                        </Composer.Field>
                    </Composer.Frame>
                    <Composer.Submit data-attr="today-report-prompt-submit" />
                </Composer.Root>
            )}
        </div>
    )
}
