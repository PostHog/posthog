import { Link } from '@posthog/lemon-ui'

export function ManualCaptureNotice(): JSX.Element {
    return (
        <p className="text-muted mt-2">
            Not using Node.js or Python? Use the{' '}
            <Link to="https://posthog.com/docs/llm-analytics/manual-capture" target="_blank">
                manual capture method
            </Link>
            .
        </p>
    )
}
