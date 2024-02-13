import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { SDKInstallPythonInstructions } from '../sdk-install-instructions'

function PythonCaptureSnippet(): JSX.Element {
    return <CodeSnippet language={Language.Python}>posthog.capture('test-id', 'test-event')</CodeSnippet>
}

export function ProductAnalyticsPythonInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallPythonInstructions />
            <h3>Send an Event</h3>
            <PythonCaptureSnippet />
        </>
    )
}
