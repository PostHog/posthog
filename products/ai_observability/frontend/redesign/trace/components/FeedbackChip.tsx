import { IconMessage, IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { FeedbackChipData } from '../types'
import { ChipButton } from './ChipButton'

export interface FeedbackChipProps {
    chip: FeedbackChipData
    onClick: () => void
}

export function FeedbackChip({ chip, onClick }: FeedbackChipProps): JSX.Element {
    const hasThumbs = chip.thumbsUp + chip.thumbsDown > 0
    return (
        <Tooltip title="Show the feedback on this trace">
            <ChipButton
                icon={hasThumbs ? undefined : <IconMessage />}
                onClick={onClick}
                aria-label={
                    hasThumbs
                        ? `${chip.thumbsUp} thumbs up, ${chip.thumbsDown} thumbs down, ${chip.total} feedback in total`
                        : undefined
                }
                data-attr="trace-view-feedback-chip"
            >
                {hasThumbs ? (
                    <span className="flex items-center gap-1">
                        <IconThumbsUp />
                        <span>{chip.thumbsUp}</span>
                        <IconThumbsDown />
                        <span>{chip.thumbsDown}</span>
                        <span className="text-secondary">·</span>
                        <span>{`Feedback ${chip.total}`}</span>
                    </span>
                ) : (
                    `Feedback ${chip.total}`
                )}
            </ChipButton>
        </Tooltip>
    )
}
