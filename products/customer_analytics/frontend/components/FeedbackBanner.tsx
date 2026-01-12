import { LemonBanner } from '@posthog/lemon-ui'

interface FeedbackBannerProps {
    feedbackButtonId: string
}

export function FeedbackBanner({ feedbackButtonId }: FeedbackBannerProps): JSX.Element {
    return (
        <LemonBanner
            type="info"
            className="mb-2 mt-2"
            action={{ children: 'Send feedback', id: `customer-analytics-${feedbackButtonId}-feedback-button` }}
        >
            We're working on improving the persons experience. Send us your feedback!
        </LemonBanner>
    )
}
