import React from 'react'
import Snippet from './snippet'

function PythonInstallSnippet() {
    return (
        <Snippet>
            <span>{'pip install posthog'}</span>
        </Snippet>
    )
}

function PythonSetupSnippet({ user }) {
    let url = window.location.origin
    return (
        <Snippet>
            <span>{'import posthog'}</span>
            <br></br>
            <br></br>
            <span>{"posthog.api_key = '" + user.team.api_token + "'"}</span>
            <br></br>
            <span>{"posthog.host = '" + url + "'"}</span>
        </Snippet>
    )
}

function PythonCaptureSnippet() {
    return (
        <Snippet>
            <span>{"posthog.capture('test-id', 'test-event')"}</span>
        </Snippet>
    )
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
