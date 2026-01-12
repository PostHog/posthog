import { LemonBanner } from '@posthog/lemon-ui'

interface FeedbackBannerProps {
    feedbackButtonId: string
    message?: string
}

const DEFAULT_MESSAGE = "We're working on improving the persons experience. Send us your feedback!"

export function FeedbackBanner({ feedbackButtonId, message = DEFAULT_MESSAGE }: FeedbackBannerProps): JSX.Element {
    return (
        <LemonBanner
            type="info"
            className="mb-2 mt-2"
            action={{ children: 'Send feedback', id: `customer-analytics-${feedbackButtonId}-feedback-button` }}
        >
            {message}
        </LemonBanner>
    )
}
