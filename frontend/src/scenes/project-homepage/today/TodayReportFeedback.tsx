import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { type ChangeEvent, type KeyboardEvent } from 'react'

import { IconArrowRight, IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled } from '@posthog/icons'
import { Input, Text } from '@posthog/quill'

import { useReportFeedbackCelebration } from 'products/signals/frontend/inbox/components/detail/ReportFeedbackCelebration'
import { inboxReportDetailLogic } from 'products/signals/frontend/inbox/logics/inboxReportDetailLogic'
import { SignalReport } from 'products/signals/frontend/inbox/types'

import { TodayActionButton } from './TodayActionButton'

const NOTE_MAX_LENGTH = 4000

export function TodayReportFeedback({ report }: { report: SignalReport }): JSX.Element {
    const logic = inboxReportDetailLogic({ reportId: report.id, report })
    const { feedbackSentiment, feedbackNoteDraft, feedbackNoteSent, feedbackSentNote, feedbackNoteSubmitting } =
        useValues(logic)
    const { rateReport, setFeedbackNoteDraft, submitFeedbackNote } = useActions(logic)
    const { celebrate, celebration } = useReportFeedbackCelebration()
    const isPositive = feedbackSentiment === 'positive'
    const isNegative = feedbackSentiment === 'negative'
    const sendNote = (): void => {
        if (feedbackNoteDraft.trim()) {
            submitFeedbackNote(feedbackNoteDraft, 'today')
        }
    }

    return (
        <div className="flex flex-col gap-2" data-attr="today-report-feedback">
            <div className="flex flex-wrap items-center gap-1">
                {/* Both labels share one grid cell so the thumbs sit still when the text swaps. */}
                <Text size="xs" variant="muted" render={<span />} className="me-1 grid">
                    <span
                        className={clsx('col-start-1 row-start-1', feedbackSentiment && 'invisible')}
                        aria-hidden={!!feedbackSentiment}
                    >
                        Was this report useful?
                    </span>
                    <span
                        className={clsx('col-start-1 row-start-1', !feedbackSentiment && 'invisible')}
                        aria-hidden={!feedbackSentiment}
                    >
                        Thanks for the feedback!
                    </span>
                </Text>
                <span className="relative inline-flex">
                    <TodayActionButton
                        size="icon-sm"
                        aria-label="This report was useful"
                        aria-pressed={isPositive}
                        tooltip="Yes, this was useful"
                        onClick={() => {
                            if (!isPositive) {
                                rateReport('positive', 'today')
                                celebrate()
                            }
                        }}
                        data-attr="today-report-feedback-up"
                    >
                        {isPositive ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                    </TodayActionButton>
                    {celebration}
                </span>
                <TodayActionButton
                    size="icon-sm"
                    aria-label="This report was not useful"
                    aria-pressed={isNegative}
                    tooltip="No, this wasn't useful"
                    onClick={() => !isNegative && rateReport('negative', 'today')}
                    data-attr="today-report-feedback-down"
                >
                    {isNegative ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                </TodayActionButton>
            </div>
            {/* The note lives under the row so it never pushes the thumbs sideways. */}
            {feedbackSentiment && !feedbackNoteSent && (
                <div className="flex w-full max-w-64 items-center gap-1">
                    <Input
                        value={feedbackNoteDraft}
                        onChange={(event: ChangeEvent<HTMLInputElement>) => setFeedbackNoteDraft(event.target.value)}
                        onKeyDown={(event: KeyboardEvent<HTMLInputElement>) => {
                            if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
                                event.preventDefault()
                                sendNote()
                            }
                        }}
                        placeholder="What was useful or off?"
                        aria-label="Add a note about this report"
                        maxLength={NOTE_MAX_LENGTH}
                        // Same height as the icon-sm thumbs next to it.
                        className="h-6 min-w-0 flex-1"
                        data-attr="today-report-feedback-note"
                    />
                    <TodayActionButton
                        variant="primary"
                        size="icon-sm"
                        aria-label="Send note"
                        tooltip="Send note"
                        loading={feedbackNoteSubmitting}
                        disabledReason={feedbackNoteDraft.trim() ? null : 'Write a note first'}
                        onClick={sendNote}
                        data-attr="today-report-feedback-note-send"
                    >
                        <IconArrowRight />
                    </TodayActionButton>
                </div>
            )}
            {feedbackNoteSent && (
                <Text size="xs" variant="muted" render={<p className="m-0 max-w-64" />}>
                    Note added: {feedbackSentNote}
                </Text>
            )}
        </div>
    )
}
