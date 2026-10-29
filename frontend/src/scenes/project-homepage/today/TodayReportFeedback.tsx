import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { type ChangeEvent, type KeyboardEvent, useState } from 'react'

import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled, IconX } from '@posthog/icons'
import { Button, Text, Textarea } from '@posthog/quill'

import { useReportFeedbackCelebration } from 'products/signals/frontend/inbox/components/detail/ReportFeedbackCelebration'
import { inboxReportDetailLogic } from 'products/signals/frontend/inbox/logics/inboxReportDetailLogic'
import { SignalReport } from 'products/signals/frontend/inbox/types'

const NOTE_MAX_LENGTH = 4000

export function TodayReportFeedback({ report }: { report: SignalReport }): JSX.Element {
    const logic = inboxReportDetailLogic({ reportId: report.id, report })
    const {
        feedbackSentiment,
        feedbackNoteDraft,
        feedbackNoteSent,
        feedbackSentNote,
        feedbackNoteSubmitting,
        feedbackDisabledReason,
    } = useValues(logic)
    const { rateReport, setFeedbackNoteDraft, submitFeedbackNote } = useActions(logic)
    const { celebrate, celebration } = useReportFeedbackCelebration()
    const isPositive = feedbackSentiment === 'positive'
    const isNegative = feedbackSentiment === 'negative'
    const [askedHere, setAskedHere] = useState(false)
    const [questionDismissed, setQuestionDismissed] = useState(false)
    const sendNote = (): void => {
        if (feedbackNoteDraft.trim()) {
            submitFeedbackNote(feedbackNoteDraft, 'today')
        }
    }
    const askingWhy = !!feedbackSentiment && !feedbackNoteSent && !questionDismissed

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
                    <Button
                        size="icon-sm"
                        aria-label="This report was useful"
                        aria-pressed={isPositive}
                        tooltip={feedbackDisabledReason ?? (isPositive ? 'Remove thumbs up' : 'Yes, this was useful')}
                        disabled={!!feedbackDisabledReason}
                        onClick={() => {
                            rateReport(isPositive ? null : 'positive', 'today', !isPositive ? celebrate : undefined)
                            setQuestionDismissed(false)
                            setAskedHere(true)
                        }}
                        data-attr="today-report-feedback-up"
                    >
                        {isPositive ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                    </Button>
                    {celebration}
                </span>
                <Button
                    size="icon-sm"
                    aria-label="This report was not useful"
                    aria-pressed={isNegative}
                    tooltip={feedbackDisabledReason ?? (isNegative ? 'Remove thumbs down' : "No, this wasn't useful")}
                    disabled={!!feedbackDisabledReason}
                    onClick={() => {
                        rateReport(isNegative ? null : 'negative', 'today')
                        setQuestionDismissed(false)
                        setAskedHere(true)
                    }}
                    data-attr="today-report-feedback-down"
                >
                    {isNegative ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                </Button>
            </div>
            {/* The question lives under the row so it never pushes the thumbs sideways. */}
            {askingWhy && (
                <div
                    className="flex w-full max-w-96 flex-col gap-1.5 rounded-md border border-primary p-2"
                    data-attr="today-report-feedback-question"
                >
                    <div className="flex items-center gap-1">
                        <Text size="xs" weight="medium" render={<span />} className="grow">
                            {isPositive ? 'What made it useful?' : 'What was off?'}
                        </Text>
                        <Button
                            size="icon-sm"
                            aria-label="Dismiss"
                            onClick={() => setQuestionDismissed(true)}
                            data-attr="today-report-feedback-question-dismiss"
                        >
                            <IconX />
                        </Button>
                    </div>
                    <div className="flex items-end gap-1.5">
                        <Textarea
                            value={feedbackNoteDraft}
                            disabled={feedbackNoteSubmitting}
                            onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
                                setFeedbackNoteDraft(event.target.value)
                            }
                            onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => {
                                if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                                    event.preventDefault()
                                    sendNote()
                                }
                            }}
                            placeholder="Your note improves future reports"
                            aria-label="Add a note about this report"
                            maxLength={NOTE_MAX_LENGTH}
                            rows={2}
                            autoFocus={askedHere}
                            className="max-h-48 min-h-14! min-w-0 flex-1 resize-none"
                            data-attr="today-report-feedback-note"
                        />
                        {/* Shown only once there is text, so there is never a disabled button to look at. */}
                        {feedbackNoteDraft.trim() && (
                            <Button
                                variant="primary"
                                size="sm"
                                loading={feedbackNoteSubmitting}
                                onClick={sendNote}
                                data-attr="today-report-feedback-note-send"
                            >
                                Send
                            </Button>
                        )}
                    </div>
                </div>
            )}
            {feedbackNoteSent && (
                <Text size="xs" variant="muted" render={<p className="m-0 max-w-96" />}>
                    Note added: {feedbackSentNote}
                </Text>
            )}
        </div>
    )
}
