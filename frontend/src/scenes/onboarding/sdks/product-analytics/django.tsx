import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { SDKInstallDjangoInstructions } from '../sdk-install-instructions'

function DjangoCaptureSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Python}>{`import posthog
    
posthog.capture('test-id', 'test-event')`}</CodeSnippet>
    )
}

export function ProductAnalyticsDjangoInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallDjangoInstructions />
            <h3>Send an Event</h3>
            <DjangoCaptureSnippet />
        </>
    )
}
