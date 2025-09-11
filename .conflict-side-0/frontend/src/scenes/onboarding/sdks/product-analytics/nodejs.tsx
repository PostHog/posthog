import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { SDKInstallNodeInstructions } from '../sdk-install-instructions'

function NodeCaptureSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript}>
            {`client.capture({
    distinctId: 'test-id',
    event: 'test-event'
})

// Send queued events immediately. Use for example in a serverless environment
// where the program may terminate before everything is sent.
// Use \`client.flush()\` instead if you still need to send more events or fetch feature flags.
client.shutdown()`}
        </CodeSnippet>
    )
}

export function ProductAnalyticsNodeInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallNodeInstructions />
            <h3>Send an Event</h3>
            <NodeCaptureSnippet />
        </>
    )
}
