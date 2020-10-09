import React from 'react'
import { CodeSnippet, Language } from './CodeSnippet'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'

function PythonInstallSnippet(): JSX.Element {
    return <CodeSnippet language={Language.Bash}>{'pip install posthog'}</CodeSnippet>
}

function PythonSetupSnippet(): JSX.Element {
    const { user } = useValues(userLogic)
    return (
        <CodeSnippet language={Language.Python}>
            {`import posthog

posthog.api_key = '${user?.team?.api_token}'
posthog.host = '${window.location.origin}'`}
        </CodeSnippet>
    )
}

function PythonCaptureSnippet(): JSX.Element {
    return <CodeSnippet language={Language.Python}>{"posthog.capture('test-id', 'test-event')"}</CodeSnippet>
}

export function PythonInstructions(): JSX.Element {
    return (
        <>
            <h3>Install</h3>
            <PythonInstallSnippet />
            <h3>Configure</h3>
            <PythonSetupSnippet />
            <h3>Send an Event</h3>
            <PythonCaptureSnippet />
        </>
    )
}
