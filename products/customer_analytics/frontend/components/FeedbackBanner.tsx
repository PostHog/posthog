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
            Customer analytics is in beta. Please let us know what you'd like to see here and/or report any issues
            directly to us!
        </LemonBanner>
    )
}
