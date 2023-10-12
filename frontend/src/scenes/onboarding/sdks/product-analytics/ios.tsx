import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { SDKInstallIOSInstructions } from '../sdk-install-instructions'

function IOS_OBJ_C_CaptureSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.ObjectiveC}>
            {'[[PHGPostHog sharedPostHog] capture:@"Test Event"];'}
        </CodeSnippet>
    )
}

function IOS_SWIFT_CaptureSnippet(): JSX.Element {
    return <CodeSnippet language={Language.Swift}>{'posthog.capture("Test Event")'}</CodeSnippet>
}

export function ProductAnalyticsIOSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallIOSInstructions />
            <h3>Send an event with swift</h3>
            <IOS_SWIFT_CaptureSnippet />
            <h3>Send an event with Objective-C</h3>
            <IOS_OBJ_C_CaptureSnippet />
        </>
    )
}
