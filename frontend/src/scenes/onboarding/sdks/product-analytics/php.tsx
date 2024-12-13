import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { SDKInstallPHPInstructions } from '../sdk-install-instructions'
import { PersonModeEventPropertyInstructions } from '../shared-snippets'

function PHPCaptureSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.PHP}>
            {"PostHog::capture(array(\n    'distinctId' => 'test-user',\n    'event' => 'test-event'\n));"}
        </CodeSnippet>
    )
}

export function ProductAnalyticsPHPInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallPHPInstructions />
            <h3>Send an Event</h3>
            <PHPCaptureSnippet />
            <PersonModeEventPropertyInstructions />
        </>
    )
}
