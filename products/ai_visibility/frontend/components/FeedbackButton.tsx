import { IconMessage } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

/**
 * This button does not have any logic attached to it, as that's added using a survey from PostHog.
 * On prod, the survey is https://us.posthog.com/project/2/surveys/019b09dc-473b-0000-4f60-383da45bedd0
 */
export function FeedbackButton(): JSX.Element {
    return (
        <LemonButton
            size="small"
            id="ai-visibility-feedback-button"
            icon={<IconMessage />}
            type="secondary"
            tooltip="Share your thoughts on AI visibility"
        >
            Feedback
        </LemonButton>
    )
}
