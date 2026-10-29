import { IconMessage } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { FeedbackChipData } from '../types'

export interface FeedbackChipProps {
    chip: FeedbackChipData
    onClick: () => void
}

export function FeedbackChip({ chip, onClick }: FeedbackChipProps): JSX.Element {
    return (
        <LemonButton
            size="xsmall"
            type="secondary"
            icon={<IconMessage />}
            onClick={onClick}
            tooltip="Show the feedback on this trace"
            data-attr="trace-view-feedback-chip"
        >
            {`Feedback ${chip.total}`}
        </LemonButton>
    )
}
