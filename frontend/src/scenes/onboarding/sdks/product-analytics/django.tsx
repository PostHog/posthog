import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { SDKInstallDjangoInstructions } from '../sdk-install-instructions'
import { PersonModeEventPropertyInstructions } from '../shared-snippets'

function DjangoCaptureSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Python}>{`import posthog

posthog.capture("user_signed_up", properties={"example_property": "with_some_value"})`}</CodeSnippet>
    )
}

export function ProductAnalyticsDjangoInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallDjangoInstructions />
            <h3>Send an Event</h3>
            <DjangoCaptureSnippet />
            <PersonModeEventPropertyInstructions />
        </>
    )
}
