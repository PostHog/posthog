import { Link } from 'lib/lemon-ui/Link'

export function ManualCaptureNotice(): JSX.Element {
    return (
        <p className="text-muted mt-2">
            Not using Node.js or Python? Use the{' '}
            <Link to="https://posthog.com/docs/llm-analytics/manual-capture" target="_blank" disableDocsPanel>
                manual capture method
            </Link>
            .
        </p>
    )
}
