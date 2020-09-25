import React from 'react'
import { CodeSnippet } from './CodeSnippet'
import '../onboardingWizard.scss'

function JSInstallSnippet() {
    return (
        <CodeSnippet language="bash">
            {['npm install posthog-js', '# OR', 'yarn add posthog-js'].join('\n')}
        </CodeSnippet>
    )
}

function JSSetupSnippet({ user }) {
    return (
        <CodeSnippet language="javascript">
            {[
                "import posthog from 'posthog-js'",
                '',
                `posthog.init('${user.team.api_token}', { api_host: '${window.location.origin}' })`,
            ].join('\n')}
        </CodeSnippet>
    )
}

function JSEventSnippet() {
    return <CodeSnippet language="javascript">{`posthog.capture('custom event', { property: 'value' })`}</CodeSnippet>
}

export function JSInstructions({ user }) {
    return (
        <>
            <h3>Install</h3>
            <JSInstallSnippet />
            <h3>Configure</h3>
            <JSSetupSnippet user={user}></JSSetupSnippet>
            <h3>Send an Event</h3>
            <JSEventSnippet />
        </>
    )
}
