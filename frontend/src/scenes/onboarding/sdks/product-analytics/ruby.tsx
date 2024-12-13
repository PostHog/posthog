import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { SDKInstallRubyInstructions } from '../sdk-install-instructions'
import { PersonModeEventPropertyInstructions } from '../shared-snippets'

function RubyCaptureSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Ruby}>
            {"posthog.capture({\n    distinct_id: 'test-id',\n    event: 'test-event'})"}
        </CodeSnippet>
    )
}

export function ProductAnalyticsRubyInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallRubyInstructions />
            <h3>Send an Event</h3>
            <RubyCaptureSnippet />
            <PersonModeEventPropertyInstructions />
        </>
    )
}
