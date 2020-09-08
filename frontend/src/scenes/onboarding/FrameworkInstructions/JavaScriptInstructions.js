import React from 'react'
import { CodeSnippet } from './CodeSnippet'
import '../onboardingWizard.scss'

function JSInstallSnippet() {
    return <CodeSnippet language="bash">{['npm install posthog-js', '# OR', 'yarn add posthog-js']}</CodeSnippet>
}

function JSSetupSnippet({ user }) {
    return (
        <CodeSnippet language="javascript">
            {[
                "import posthog from 'posthog-js'",
                `posthog.init('${user.team.api_token}', { api_host: '${window.location.origin}' })`,
            ]}
        </CodeSnippet>
    )
}

export function JSInstructions({ user }) {
    return (
        <>
            <h3>Install</h3>
            <JSInstallSnippet></JSInstallSnippet>
            <h3>Configure</h3>
            <JSSetupSnippet user={user}></JSSetupSnippet>
            <h2>Send an Event</h2>
            <p className="prompt-text">
                {"Once you've inserted the snippet, click on a button or form on your website to send an event!"}
            </p>
        </>
    )
}
