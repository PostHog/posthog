import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { SDKInstallLaravelInstructions } from '../sdk-install-instructions'
import { PersonModeEventPropertyInstructions } from '../shared-snippets'

function LaravelCaptureSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.PHP}>
            {"PostHog::capture(array(\n    'distinctId' => 'test-user',\n    'event' => 'test-event'\n));"}
        </CodeSnippet>
    )
}

export function ProductAnalyticsLaravelInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallLaravelInstructions />
            <h3>Send an Event</h3>
            <LaravelCaptureSnippet />
            <PersonModeEventPropertyInstructions />
        </>
    )
}
