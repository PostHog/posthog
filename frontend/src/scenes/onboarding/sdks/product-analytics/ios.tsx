import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { SDKInstallIOSInstructions } from '../sdk-install-instructions'

function IOSCaptureSnippet(): JSX.Element {
    return <CodeSnippet language={Language.Swift}>{`PostHogSDK.shared.capture("Test Event")`}</CodeSnippet>
}

export function ProductAnalyticsIOSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallIOSInstructions />
            <h3>Send an event</h3>
            <IOSCaptureSnippet />
        </>
    )
}
