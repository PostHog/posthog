import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconClock, IconPullRequest, IconSparkles } from '@posthog/icons'
import { Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { Composer } from 'products/posthog_ai/frontend/api/primitives'
import { captureInboxReportAction, discussQuestionProperties } from 'products/signals/frontend/inbox/inboxAnalytics'
import { inboxTaskKickoffLogic } from 'products/signals/frontend/inbox/inboxTaskKickoffLogic'
import type {
    ImplementationSlotClaim,
    ReportTaskEntry,
} from 'products/signals/frontend/inbox/logics/inboxReportDetailLogic'
import { SignalReport } from 'products/signals/frontend/inbox/types'

import { TodayActionButton } from './TodayActionButton'
import { TodayImplementMenu } from './TodayImplementMenu'
import { todayLogic } from './todayLogic'
import { startDisabledReason, todayNextStep } from './todayNextStep'
import { todayReportLogic } from './todayReportLogic'

const SAMPLE_REASON = 'Sample reports can’t start work. Turn off sample reports to use a real one.'

export function TodayReportNextStep({
    report,
    reportTaskToOpen,
    slotClaim,
}: {
    report: SignalReport
    reportTaskToOpen: ReportTaskEntry | null
    slotClaim: ImplementationSlotClaim | null
}): JSX.Element | null {
    const { createPrDisabledReason } = useValues(inboxTaskKickoffLogic)
    const { openReportTask } = useActions(inboxTaskKickoffLogic)
    const { reportState, reportUrl, isSample, sections } = useValues(todayReportLogic({ reportId: report.id }))
    const { askingAi } = useValues(todayLogic)
    const { askAi } = useActions(todayLogic)
    const [composerOpen, setComposerOpen] = useState(false)
    const [draft, setDraft] = useState('')
    const textAreaRef = useRef<HTMLTextAreaElement>(null)
    const sampleReason = isSample ? SAMPLE_REASON : null
    const task = reportTaskToOpen?.task
    const runningTask = task?.latest_run ? { taskId: task.id, runId: task.latest_run.id } : null
    const { primary, note, pickedUp } = todayNextStep(report, {
        proposal: sections.proposal,
        slotClaimed: slotClaim !== null,
        hasRun: runningTask !== null,
    })

    if (reportState !== 'open') {
        return null
    }

    const askDisabledReason = isSample
        ? 'Sample reports can’t start a chat. Turn off sample reports to ask about a real one.'
        : null
    const startReason = startDisabledReason(report, pickedUp, createPrDisabledReason)

    const openComposer = (text: string): void => {
        setComposerOpen(true)
        setDraft(text)
        requestAnimationFrame(() => {
            const textArea = textAreaRef.current
            textArea?.focus({ preventScroll: true })
            textArea?.setSelectionRange(text.length, text.length)
        })
    }

    const ask = (question: string): void => {
        if (!question || askingAi) {
            return
        }
        captureInboxReportAction({
            report,
            actionType: 'discuss',
            surface: 'today',
            extra: discussQuestionProperties({ source: 'typed', suggestionCount: 0 }),
        })
        askAi(question, 'report_page', report)
    }

    return (
        <div className="flex flex-col gap-2" data-attr="today-report-continue">
            <div className="flex flex-wrap items-center gap-1">
                {primary?.kind === 'review' && (
                    <TodayActionButton
                        variant="primary"
                        className="me-1"
                        nativeButton={false}
                        render={<LinkPrimitive to={primary.url} target="_blank" />}
                        disabledReason={sampleReason}
                        data-attr="today-report-review-pr"
                    >
                        <IconPullRequest />
                        {primary.label}
                    </TodayActionButton>
                )}
                {primary?.kind === 'open_task' && runningTask && (
                    <TodayActionButton
                        variant="primary"
                        className="me-1"
                        onClick={() => openReportTask(report, runningTask.taskId, runningTask.runId)}
                        data-attr="today-report-open-task"
                    >
                        <IconClock />
                        {primary.label}
                    </TodayActionButton>
                )}
                {primary?.kind === 'start' && (
                    <TodayImplementMenu
                        report={report}
                        reportUrl={reportUrl}
                        disabled={isSample}
                        postHogDisabledReason={startReason}
                        onStartWithPostHog={openComposer}
                    />
                )}
                <TodayActionButton
                    className={primary ? undefined : '-ms-2'}
                    onClick={() => openComposer(composerOpen ? draft : '')}
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
                    {note}
                </Text>
            )}
            {composerOpen && (
                <Composer.Root
                    value={draft}
                    onChange={setDraft}
                    onSubmit={() => {
                        ask(draft.trim())
                        setDraft('')
                    }}
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
