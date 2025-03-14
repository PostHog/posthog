import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

// function JSEventSnippet(): JSX.Element {
//     return (
//         <CodeSnippet language={Language.JavaScript}>posthog.captureException(error, additionalProperties)</CodeSnippet>
//     )
// }

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
            <p>Our package automatically captures uncaught errors and unhandled rejections in your application.</p>
            <JSManualCapture />
        </>
    )
}
