import React from 'react'
import { CodeSnippet, Language } from './CodeSnippet'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'

function JSInstallSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Bash}>
            {['npm install posthog-js', '# OR', 'yarn add posthog-js'].join('\n')}
        </CodeSnippet>
    )
}

function JSSetupSnippet(): JSX.Element {
    const { user } = useValues(userLogic)
    return (
        <CodeSnippet language={Language.JavaScript}>
            {[
                "import posthog from 'posthog-js'",
                '',
                `posthog.init('${user?.team?.api_token}', { api_host: '${window.location.origin}' })`,
            ].join('\n')}
        </CodeSnippet>
    )
}

function JSEventSnippet(): JSX.Element {
    return (
        <CodeSnippet
            language={Language.JavaScript}
        >{`posthog.capture('custom event', { property: 'value' })`}</CodeSnippet>
    )
}

export function JSInstructions(): JSX.Element {
    return (
        <>
            <h3>Install</h3>
            <JSInstallSnippet />
            <h3>Configure</h3>
            <JSSetupSnippet />
            <h3>Send an Event</h3>
            <JSEventSnippet />
        </>
    )
}
