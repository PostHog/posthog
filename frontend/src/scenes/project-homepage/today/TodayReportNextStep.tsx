import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconClock, IconSparkles } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { Composer } from 'products/posthog_ai/frontend/api/composer'
import type { InboxReportActionSurface } from 'products/signals/frontend/inbox/inboxAnalytics'
import { inboxTaskKickoffLogic } from 'products/signals/frontend/inbox/inboxTaskKickoffLogic'
import type {
    ImplementationSlotClaim,
    ReportTaskEntry,
} from 'products/signals/frontend/inbox/logics/inboxReportDetailLogic'
import { SignalReport } from 'products/signals/frontend/inbox/types'

import { startDisabledReason, todayNextStep } from './todayNextStep'
import { todayReportLogic } from './todayReportLogic'
import { TodayReportPrimaryAction } from './TodayReportPrimaryAction'
import { SAMPLE_REPORT_REASON } from './todaySampleReports'

export function TodayReportNextStep({
    report,
    reportTaskToOpen,
    slotClaim,
    surface = 'today',
}: {
    report: SignalReport
    reportTaskToOpen: ReportTaskEntry | null
    slotClaim: ImplementationSlotClaim | null
    surface?: InboxReportActionSurface
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
                    <TodayReportPrimaryAction
                        primary={primary}
                        report={report}
                        reportUrl={reportUrl}
                        isSample={isSample}
                        startReason={startDisabledReason(report, taskPickedUp, {
                            createPrDisabledReason,
                            aiConsentDisabledReason,
                        })}
                        surface={surface}
                    />
                )}
                <Button
                    className={primary ? undefined : '-ms-2'}
                    onClick={focusComposer}
                    disabledReason={askDisabledReason}
                    data-attr="today-report-ask"
                >
                    <IconSparkles />
                    Ask about it
                </Button>
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
                    onSubmit={() => askAboutReport(draft.trim(), surface)}
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
