import React from 'react'
import { CodeSnippet, Language } from './CodeSnippet'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

function PHPConfigSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.JSON}>
            {`{
    "require": {
        "posthog/posthog-php": "1.0.*"
    }
}`}
        </CodeSnippet>
    )
}

function PHPInstallSnippet(): JSX.Element {
    return <CodeSnippet language={Language.Bash}>{'php composer.phar install'}</CodeSnippet>
}

function PHPSetupSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <CodeSnippet language={Language.PHP}>
            {`PostHog::init('${currentTeam?.api_token}',
    array('host' => '${window.location.origin}')
);`}
        </CodeSnippet>
    )
}

function PHPCaptureSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.PHP}>
            {"PostHog::capture(array(\n    'distinctId' => 'test-user',\n    'event' => 'test-event'\n));"}
        </CodeSnippet>
    )
}

export function PHPInstructions(): JSX.Element {
    return (
        <>
            <h3>Dependency Setup</h3>
            <PHPConfigSnippet />
            <h3>Install</h3>
            <PHPInstallSnippet />
            <h3>Configure</h3>
            <PHPSetupSnippet />
            <h3>Send an Event</h3>
            <PHPCaptureSnippet />
        </>
    )
}
