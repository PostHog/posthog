import { IconMessage, IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import type { TraceFeedbackSummaryApi } from '../../../generated/api.schemas'
import { ChipButton } from './ChipButton'

export interface FeedbackChipProps {
    summary: TraceFeedbackSummaryApi
    onClick: () => void
}

export function FeedbackChip({ summary, onClick }: FeedbackChipProps): JSX.Element | null {
    if (summary.total === 0) {
        return null
    }
    const hasThumbs = summary.thumbsUp + summary.thumbsDown > 0
    return (
        <Tooltip title="Show the feedback on this trace">
            <ChipButton
                icon={hasThumbs ? undefined : <IconMessage />}
                onClick={onClick}
                aria-label={
                    hasThumbs
                        ? `${summary.thumbsUp} thumbs up, ${summary.thumbsDown} thumbs down, ${summary.total} feedback in total`
                        : undefined
                }
                data-attr="trace-view-feedback-chip"
            >
                {hasThumbs ? (
                    <span className="flex items-center gap-1">
                        <IconThumbsUp />
                        <span>{summary.thumbsUp}</span>
                        <IconThumbsDown />
                        <span>{summary.thumbsDown}</span>
                        <span className="text-secondary">·</span>
                        <span>{`Feedback ${summary.total}`}</span>
                    </span>
                ) : (
                    `Feedback ${summary.total}`
                )}
            </ChipButton>
        </Tooltip>
    )
}
