import React from 'react'
import { CodeSnippet } from './CodeSnippet'

function PHPConfigSnippet() {
    return (
        <CodeSnippet language="json">
            {`{
    "require": {
        "posthog/posthog-php": "1.0.*"
    }
}`}
        </CodeSnippet>
    )
}

function PHPInstallSnippet() {
    return <CodeSnippet language="bash">{'php composer.phar install'}</CodeSnippet>
}

function PHPSetupSnippet({ user }) {
    return (
        <CodeSnippet language="php">
            {`PostHog::init('${user.team.api_token}',
    array('host' => '${window.location.origin}')
);`}
        </CodeSnippet>
    )
}

function PHPCaptureSnippet() {
    return (
        <CodeSnippet language="php">
            {"PostHog::capture(array(\n    'distinctId' => 'test-user',\n    'event' => 'test-event'\n));"}
        </CodeSnippet>
    )
}

export function PHPInstructions({ user }) {
    return (
        <>
            <h3>Dependency Setup</h3>
            <PHPConfigSnippet></PHPConfigSnippet>
            <h3>Install</h3>
            <PHPInstallSnippet></PHPInstallSnippet>
            <h3>Configure</h3>
            <PHPSetupSnippet user={user}></PHPSetupSnippet>
            <h3>Send an Event</h3>
            <PHPCaptureSnippet></PHPCaptureSnippet>
        </>
    )
}
