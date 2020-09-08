import React from 'react'
import { CodeSnippet } from './CodeSnippet'

function NodeInstallSnippet() {
    return (
        <CodeSnippet language="bash">
            {`npm install posthog-node
# OR
yarn add posthog-node`}
        </CodeSnippet>
    )
}

function NodeSetupSnippet({ user }) {
    return (
        <CodeSnippet language="javascript">
            {`import PostHog from 'posthog-node'

const client = new PostHog(
    '${user.team.api_token}',
    { host: '${window.location.origin}' }
)`}
        </CodeSnippet>
    )
}

function NodeCaptureSnippet() {
    return (
        <CodeSnippet language="javascript">
            {"client.capture({\n    distinctId: 'test-id',\n    event: 'test-event'\n})"}
        </CodeSnippet>
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
