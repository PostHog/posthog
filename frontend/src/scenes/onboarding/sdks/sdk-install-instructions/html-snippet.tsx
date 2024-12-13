import { JSSnippet } from 'lib/components/JSSnippet'

export function SDKHtmlSnippetInstructions(): JSX.Element {
    return (
        <>
            <h3>Install</h3>
            <p>
                Add this snippet to your website within the <code>&lt;head&gt;</code> tag and you'll be ready to start
                using PostHog. This can also be used in services like Google Tag Manager.
            </p>
            <JSSnippet />
        </>
    )
}
