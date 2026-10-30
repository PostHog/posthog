import { IconMessage } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { StepFeedback } from '../types'

const SHOWN_SCORES = 3

export interface StepFeedbackChipsProps {
    feedback: StepFeedback
    onOpen: () => void
}

export function StepFeedbackChips({ feedback, onOpen }: StepFeedbackChipsProps): JSX.Element {
    const shown = feedback.scores.slice(0, SHOWN_SCORES)
    const hidden = feedback.scores.length - shown.length
    return (
        <>
            {shown.map((score) => (
                <LemonButton
                    key={score.id}
                    size="xsmall"
                    type="secondary"
                    onClick={onOpen}
                    tooltip="Show this score in the feedback"
                    data-attr="trace-view-feedback-step-chip"
                >
                    <span className="max-w-48 truncate font-mono">{`${score.name ?? 'Unnamed score'} ${score.value}`}</span>
                </LemonButton>
            ))}
            {hidden > 0 ? (
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    onClick={onOpen}
                    tooltip="Show all scores in the feedback"
                    data-attr="trace-view-feedback-step-chip"
                >
                    {`+${hidden}`}
                </LemonButton>
            ) : null}
            {feedback.responseCount > 0 ? (
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    icon={<IconMessage />}
                    onClick={onOpen}
                    tooltip="Show what users said"
                    data-attr="trace-view-feedback-step-chip"
                >
                    {`Feedback ${feedback.responseCount}`}
                </LemonButton>
            ) : null}
        </>
    )
}
