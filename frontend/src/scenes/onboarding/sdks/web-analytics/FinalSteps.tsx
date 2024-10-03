import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

function JSEventSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript}>{`posthog.capture('my event', { property: 'value' })`}</CodeSnippet>
    )
}

export const WebAnalyticsAllJSFinalSteps = (): JSX.Element => {
    return (
        <>
            <h4>Send events</h4>
            <p>
                Click around and view a couple pages to generate some events. Our package automatically captures them
                for you.
            </p>
            <h4>Optional: Send a manual event</h4>
            <p>If you'd like, you can manually define events, too.</p>
            <JSEventSnippet />
        </>
    )
}

export const WebAnalyticsMobileFinalSteps = (): JSX.Element => {
    return (
        <>
            <h3>Track screen views</h3>
            <p>
                Despite the name, the web analytics dashboard can be used to track screen views in mobile apps, too.
                Open your app and view some screens to generate some events.
            </p>
        </>
    )
}
