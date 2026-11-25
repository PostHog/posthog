import { useRef, useState } from 'react'

import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { AiFeedbackReasonEnumApi } from '../../generated/api.schemas'
import type { AiReplyFeedbackRating } from '../../types'

export interface AiReplyFeedbackProps {
    rating: AiReplyFeedbackRating | null
    disabledReason?: string
    onSubmit: (rating: AiReplyFeedbackRating, feedbackText?: string, reasons?: AiFeedbackReasonEnumApi[]) => void
}

const REASON_LABELS: Record<AiFeedbackReasonEnumApi, string> = {
    [AiFeedbackReasonEnumApi.WrongFacts]: 'Wrong facts',
    [AiFeedbackReasonEnumApi.MissedQuestion]: 'Missed the question',
    [AiFeedbackReasonEnumApi.TooVague]: 'Too vague',
    [AiFeedbackReasonEnumApi.WrongTone]: 'Wrong tone',
    [AiFeedbackReasonEnumApi.ShouldNotRun]: 'Should not have run',
}

const REASONS = Object.keys(REASON_LABELS) as AiFeedbackReasonEnumApi[]

export function AiReplyFeedback({ rating, disabledReason, onSubmit }: AiReplyFeedbackProps): JSX.Element {
    const [reasons, setReasons] = useState<AiFeedbackReasonEnumApi[]>([])
    const [feedbackText, setFeedbackText] = useState('')
    const [detailsSubmitted, setDetailsSubmitted] = useState(false)
    // A rating that was already there on mount was explained, or skipped, in an earlier visit.
    const wasRatedOnMount = useRef(!!rating)
    const showDetails = rating === 'bad' && !wasRatedOnMount.current && !detailsSubmitted
    const hasDetails = reasons.length > 0 || !!feedbackText.trim()
    const ratingDisabledReason = disabledReason ?? (rating ? 'Feedback already recorded' : undefined)

    function submitRating(nextRating: AiReplyFeedbackRating): void {
        if (disabledReason || rating) {
            return
        }
        onSubmit(nextRating)
    }

    function toggleReason(reason: AiFeedbackReasonEnumApi): void {
        setReasons((current) =>
            current.includes(reason) ? current.filter((item) => item !== reason) : [...current, reason]
        )
    }

    function submitDetails(): void {
        if (disabledReason || !hasDetails) {
            return
        }
        onSubmit('bad', feedbackText.trim() || undefined, reasons.length > 0 ? reasons : undefined)
        setDetailsSubmitted(true)
    }

    return (
        <div className="mt-1.5 space-y-1.5">
            <div className="flex flex-wrap items-center gap-1">
                {!rating && <span className="text-xs text-muted-alt mr-1">Was this useful?</span>}
                {rating !== 'bad' && (
                    <LemonButton
                        icon={rating === 'good' ? <IconThumbsUpFilled /> : <IconThumbsUp />}
                        type="tertiary"
                        size="xsmall"
                        disabledReason={ratingDisabledReason}
                        onClick={() => submitRating('good')}
                        // pinned: autocapture key. Do not rename.
                        data-attr="ai-reply-feedback-good"
                    >
                        Useful
                    </LemonButton>
                )}
                {rating !== 'good' && (
                    <LemonButton
                        icon={rating === 'bad' ? <IconThumbsDownFilled /> : <IconThumbsDown />}
                        type="tertiary"
                        size="xsmall"
                        disabledReason={ratingDisabledReason}
                        onClick={() => submitRating('bad')}
                        // pinned: autocapture key. Do not rename.
                        data-attr="ai-reply-feedback-bad"
                    >
                        Not useful
                    </LemonButton>
                )}
            </div>
            {showDetails && (
                <div className="space-y-1.5">
                    <div className="text-xs text-muted-alt">What was wrong? Pick any that apply.</div>
                    <div className="flex flex-wrap gap-1">
                        {REASONS.map((reason) => (
                            <LemonButton
                                key={reason}
                                type="secondary"
                                size="xsmall"
                                active={reasons.includes(reason)}
                                disabledReason={disabledReason}
                                onClick={() => toggleReason(reason)}
                                data-attr={`ai-reply-feedback-reason-${reason}`}
                            >
                                {REASON_LABELS[reason]}
                            </LemonButton>
                        ))}
                    </div>
                    <div className="flex w-full gap-1.5 items-center">
                        <LemonInput
                            placeholder="Add details (optional)"
                            fullWidth
                            size="small"
                            value={feedbackText}
                            onChange={setFeedbackText}
                            onPressEnter={submitDetails}
                            disabledReason={disabledReason}
                        />
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={submitDetails}
                            disabledReason={
                                disabledReason ?? (!hasDetails ? 'Pick a reason or add details' : undefined)
                            }
                            data-attr="ai-reply-feedback-submit"
                        >
                            Send
                        </LemonButton>
                    </div>
                </div>
            )}
            {rating === 'bad' && detailsSubmitted && (
                <span className="text-xs text-muted-alt">Thanks for your feedback</span>
            )}
        </div>
    )
}
