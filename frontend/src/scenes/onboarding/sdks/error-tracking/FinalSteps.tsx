import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

export function NodeManualCapture(): JSX.Element {
    return (
        <>
            <h4>Optional: Capture exceptions manually</h4>
            <p>If you'd like, you can manually capture exceptions that you handle in your application.</p>
            <CodeSnippet language={Language.JavaScript}>
                posthog.captureException(error, 'user_distinct_id', additionalProperties)
            </CodeSnippet>
        </>
    )
}

export function JSManualCapture(): JSX.Element {
    return (
        <>
            <h4>Optional: Capture exceptions manually</h4>
            <p>If you'd like, you can manually capture exceptions that you handle in your application.</p>
            <CodeSnippet language={Language.JavaScript}>
                posthog.captureException(error, additionalProperties)
            </CodeSnippet>
        </>
    )
}

export const ErrorTrackingAllJSFinalSteps = (): JSX.Element => {
    return (
        <>
            <h3>Capturing exceptions</h3>
            <p>Our SDK captures all errors and unhandled rejections in your application by default.</p>
            <JSManualCapture />
        </>
    )
}
