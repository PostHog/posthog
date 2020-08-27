import React from 'react'
import { CodeSnippet } from './CodeSnippet'

function PythonInstallSnippet() {
    return <CodeSnippet language="bash">{'pip install posthog'}</CodeSnippet>
}

function PythonSetupSnippet({ user }) {
    return (
        <CodeSnippet language="python">
            {`import posthog

posthog.api_key = '${user.team.api_token}'
posthog.host = '${window.location.origin}'`}
        </CodeSnippet>
    )
}

function PythonCaptureSnippet() {
    return <CodeSnippet language="python">{"posthog.capture('test-id', 'test-event')"}</CodeSnippet>
}

export function PythonInstructions({ user }) {
    return (
        <>
            <h3>Install</h3>
            <PythonInstallSnippet></PythonInstallSnippet>
            <h3>Configure</h3>
            <PythonSetupSnippet user={user}></PythonSetupSnippet>
            <h3>Send an Event</h3>
            <PythonCaptureSnippet></PythonCaptureSnippet>
        </>
    )
}
