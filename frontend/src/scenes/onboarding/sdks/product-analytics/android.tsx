import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { SDKInstallAndroidInstructions } from '../sdk-install-instructions'

function AndroidCaptureSnippet(): JSX.Element {
    return <CodeSnippet language={Language.Java}>PostHog.with(this).capture("test-event");</CodeSnippet>
}

export function ProductAnalyticsAndroidInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallAndroidInstructions />
            <h3>Send an Event</h3>
            <AndroidCaptureSnippet />
        </>
    )
}
