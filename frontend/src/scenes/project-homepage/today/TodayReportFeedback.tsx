import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { type ChangeEvent, type KeyboardEvent, useState } from 'react'

import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled, IconX } from '@posthog/icons'
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
                    <TodayActionButton
                        size="icon-sm"
                        aria-label="This report was useful"
                        aria-pressed={isPositive}
                        tooltip="Yes, this was useful"
                        onClick={() => {
                            if (!isPositive) {
                                rateReport('positive', 'today')
                                setQuestionDismissed(false)
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
                    onClick={() => {
                        if (!isNegative) {
                            rateReport('negative', 'today')
                            setQuestionDismissed(false)
                        }
                    }}
                    data-attr="today-report-feedback-down"
                >
                    {isNegative ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                </TodayActionButton>
            </div>
            {/* The question lives under the row so it never pushes the thumbs sideways. */}
            {askingWhy && (
                <div
                    className="flex w-full max-w-80 flex-col gap-1.5 rounded-md border border-primary p-2"
                    data-attr="today-report-feedback-question"
                >
                    <div className="flex items-center gap-1">
                        <Text size="xs" weight="medium" render={<span />} className="grow">
                            {isPositive ? 'What made it useful?' : 'What was off?'}
                        </Text>
                        <TodayActionButton
                            size="icon-sm"
                            aria-label="Dismiss"
                            onClick={() => setQuestionDismissed(true)}
                            data-attr="today-report-feedback-question-dismiss"
                        >
                            <IconX />
                        </TodayActionButton>
                    </div>
                    <div className="flex items-center gap-1.5">
                        <Input
                            value={feedbackNoteDraft}
                            onChange={(event: ChangeEvent<HTMLInputElement>) =>
                                setFeedbackNoteDraft(event.target.value)
                            }
                            onKeyDown={(event: KeyboardEvent<HTMLInputElement>) => {
                                if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
                                    event.preventDefault()
                                    sendNote()
                                }
                            }}
                            placeholder="Your note goes to the scout that wrote this"
                            aria-label="Add a note about this report"
                            maxLength={NOTE_MAX_LENGTH}
                            autoFocus
                            className="min-w-0 flex-1"
                            data-attr="today-report-feedback-note"
                        />
                        {/* Shown only once there is text, so there is never a disabled button to look at. */}
                        {feedbackNoteDraft.trim() && (
                            <TodayActionButton
                                variant="primary"
                                size="sm"
                                loading={feedbackNoteSubmitting}
                                onClick={sendNote}
                                data-attr="today-report-feedback-note-send"
                            >
                                Send
                            </TodayActionButton>
                        )}
                    </div>
                </div>
            )}
            {feedbackNoteSent && (
                <Text size="xs" variant="muted" render={<p className="m-0 max-w-80" />}>
                    Note added: {feedbackSentNote}
                </Text>
            )}
        </div>
    )
}
