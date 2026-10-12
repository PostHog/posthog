import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { type ChangeEvent } from 'react'

import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled } from '@posthog/icons'
import { Button, Text, Textarea } from '@posthog/quill'

import { useReportFeedbackCelebration } from 'products/signals/frontend/inbox/components/detail/ReportFeedbackCelebration'
import { inboxReportDetailLogic } from 'products/signals/frontend/inbox/logics/inboxReportDetailLogic'
import { SignalReport } from 'products/signals/frontend/inbox/types'

import { TodayActionButton } from './TodayActionButton'
import { todayReportLogic } from './todayReportLogic'

const NOTE_MAX_LENGTH = 4000

export function TodayReportFeedback({ report }: { report: SignalReport }): JSX.Element {
    const logic = inboxReportDetailLogic({ reportId: report.id, report })
    const { feedbackSentiment, feedbackNoteOpen, feedbackNoteDraft, feedbackNoteSent, feedbackNoteSubmitting } =
        useValues(logic)
    const { rateReport, openFeedbackNote, setFeedbackNoteDraft, submitFeedbackNote } = useActions(logic)
    const { feedbackNoteFocused } = useValues(todayReportLogic({ reportId: report.id }))
    const { focusFeedbackNote } = useActions(todayReportLogic({ reportId: report.id }))
    const { celebrate, celebration } = useReportFeedbackCelebration()
    const isPositive = feedbackSentiment === 'positive'
    const isNegative = feedbackSentiment === 'negative'
    const canAddNote = !!feedbackSentiment && !feedbackNoteOpen && !feedbackNoteSent

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
            {/* The note controls live under the row so they never push the thumbs sideways. */}
            {canAddNote && (
                <Button
                    variant="link-muted"
                    size="sm"
                    className="self-start"
                    onClick={() => {
                        focusFeedbackNote()
                        openFeedbackNote()
                    }}
                    data-attr="today-report-feedback-note-open"
                >
                    Add a note
                </Button>
            )}
            {feedbackNoteSent && (
                <Text size="xs" variant="muted" render={<span />}>
                    Note added
                </Text>
            )}
            {feedbackNoteOpen && (
                <div className="flex flex-col items-start gap-2">
                    <Textarea
                        value={feedbackNoteDraft}
                        onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setFeedbackNoteDraft(event.target.value)}
                        placeholder="What was useful or off?"
                        aria-label="Add a note about this report"
                        maxLength={NOTE_MAX_LENGTH}
                        rows={4}
                        autoFocus={feedbackNoteFocused}
                        className="w-full"
                        data-attr="today-report-feedback-note"
                    />
                    <TodayActionButton
                        variant="primary"
                        size="sm"
                        loading={feedbackNoteSubmitting}
                        disabledReason={feedbackNoteDraft.trim() ? null : 'Write a note first'}
                        onClick={() => submitFeedbackNote(feedbackNoteDraft, 'today')}
                        data-attr="today-report-feedback-note-send"
                    >
                        Send
                    </TodayActionButton>
                </div>
            )}
        </div>
    )
}
