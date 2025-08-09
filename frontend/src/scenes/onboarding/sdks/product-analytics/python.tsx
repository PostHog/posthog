import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { SDKInstallPythonInstructions } from '../sdk-install-instructions'
import { PersonModeEventPropertyInstructions } from '../shared-snippets'

function PythonCaptureSnippet(): JSX.Element {
    return (
        <CodeSnippet
            language={Language.Python}
        >{`posthog.capture("user_signed_up", properties={"example_property": "with_some_value"})`}</CodeSnippet>
    )
}

export function ProductAnalyticsPythonInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallPythonInstructions />
            <h3>Send an Event</h3>
            <PythonCaptureSnippet />
            <PersonModeEventPropertyInstructions />
        </>
    )
}
