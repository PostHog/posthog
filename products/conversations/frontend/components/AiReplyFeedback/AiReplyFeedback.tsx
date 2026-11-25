import { useRef, useState } from 'react'

import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import type { AiFeedbackReasonEnumApi } from '../../generated/api.schemas'
import type { AiReplyFeedbackRating } from '../../types'
import { AiReplyFeedbackDetails } from '../AiReplyFeedbackDetails/AiReplyFeedbackDetails'

export interface AiReplyFeedbackProps {
    rating: AiReplyFeedbackRating | null
    disabledReason?: string
    onSubmit: (rating: AiReplyFeedbackRating, feedbackText?: string, reasons?: AiFeedbackReasonEnumApi[]) => void
}

// pinned: the `dataAttr` values are autocapture keys. Do not rename.
const RATING_BUTTONS = [
    {
        rating: 'good',
        label: 'Useful',
        icon: <IconThumbsUp />,
        selectedIcon: <IconThumbsUpFilled />,
        dataAttr: 'ai-reply-feedback-good',
    },
    {
        rating: 'bad',
        label: 'Not useful',
        icon: <IconThumbsDown />,
        selectedIcon: <IconThumbsDownFilled />,
        dataAttr: 'ai-reply-feedback-bad',
    },
] as const

export function AiReplyFeedback({ rating, disabledReason, onSubmit }: AiReplyFeedbackProps): JSX.Element {
    const [detailsSubmitted, setDetailsSubmitted] = useState(false)
    // A rating that was already there on mount was explained, or skipped, in an earlier visit.
    const wasRatedOnMount = useRef(!!rating)
    const isBad = rating === 'bad'
    const ratingDisabledReason = disabledReason ?? (rating ? 'Feedback already recorded' : undefined)
    const visibleButtons = RATING_BUTTONS.filter((button) => !rating || button.rating === rating)

    function submitDetails(feedbackText?: string, reasons?: AiFeedbackReasonEnumApi[]): void {
        onSubmit('bad', feedbackText, reasons)
        setDetailsSubmitted(true)
    }

    return (
        <div className="mt-1.5 space-y-1.5">
            <div className="flex flex-wrap items-center gap-1">
                {!rating && <span className="text-xs text-muted-alt mr-1">Was this useful?</span>}
                {visibleButtons.map((button) => (
                    <LemonButton
                        key={button.rating}
                        icon={rating ? button.selectedIcon : button.icon}
                        type="tertiary"
                        size="xsmall"
                        disabledReason={ratingDisabledReason}
                        onClick={() => onSubmit(button.rating)}
                        data-attr={button.dataAttr}
                    >
                        {button.label}
                    </LemonButton>
                ))}
            </div>
            {isBad && !wasRatedOnMount.current && !detailsSubmitted && (
                <AiReplyFeedbackDetails disabledReason={disabledReason} onSubmit={submitDetails} />
            )}
            {isBad && detailsSubmitted && <span className="text-xs text-muted-alt">Thanks for your feedback</span>}
        </div>
    )
}
