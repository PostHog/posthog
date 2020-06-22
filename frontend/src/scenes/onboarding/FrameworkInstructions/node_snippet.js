import React from 'react'
import Snippet from './snippet'

function NodeInstallSnippet() {
    return (
        <Snippet>
            <span>{'npm install posthog-node'}</span>
            <br></br>
            <span>{'// or'}</span>
            <br></br>
            <span>{'yarn add posthog-node'}</span>
        </Snippet>
    )
}

function NodeSetupSnippet({ user }) {
    let url = window.location.origin
    return (
        <Snippet>
            <span>{"import PostHog from 'posthog-node'"}</span>
            <br></br>
            <span>{'const client = new PostHog('}</span>
            <br></br>
            <span>{'    ' + user.team.api_token + ','}</span>
            <br></br>
            <span>{'    { host: ' + url + ' }'}</span>
            <br></br>
            <span>{')'}</span>
        </Snippet>
    )
}

function NodeCaptureSnippet() {
    return (
        <Snippet>
            <span>{"client.capture({\n    distinctId: 'test-id',\n    event: 'test-event'\n})"}</span>
        </Snippet>
    )
}

export function NodeInstructions({ user }) {
    return (
        <>
            <h3>Install</h3>
            <NodeInstallSnippet></NodeInstallSnippet>
            <h3>Configure</h3>
            <NodeSetupSnippet user={user}></NodeSetupSnippet>
            <h3>Send an Event</h3>
            <NodeCaptureSnippet></NodeCaptureSnippet>
        </>
    )
}
