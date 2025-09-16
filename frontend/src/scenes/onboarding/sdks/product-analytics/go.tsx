import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { SDKInstallGoInstructions } from '../sdk-install-instructions'
import { PersonModeEventPropertyInstructions } from '../shared-snippets'

function GoCaptureSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Go}>
            {'client.Enqueue(posthog.Capture{\n    DistinctId: "test-user",\n    Event: "test-snippet",\n})'}
        </CodeSnippet>
    )
}

export function ProductAnalyticsGoInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallGoInstructions />
            <h3>Send an Event</h3>
            <GoCaptureSnippet />
            <PersonModeEventPropertyInstructions />
        </>
    )
}
