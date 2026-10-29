import { Link } from '@posthog/lemon-ui'

const FEEDBACK_DOCS_URL = 'https://posthog.com/docs/ai-observability/collect-user-feedback'

export function FeedbackEmptyState(): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <p className="m-0 text-secondary">
                No feedback on this trace yet. Feedback shows here when your code sends scores or comments for it.
            </p>
            <Link to={FEEDBACK_DOCS_URL} target="_blank" data-attr="trace-view-feedback-docs-link">
                Send feedback from your code
            </Link>
        </div>
    )
}
