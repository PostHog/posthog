import React from 'react'
import Snippet from './snippet'

function PHPConfigSnippet() {
    return (
        <Snippet>
            <span>{'{'}</span>
            <br></br>
            <span>{'    "require": {'}</span>
            <br></br>
            <span>{'        "posthog/posthog-php": "1.0.*"'}</span>
            <br></br>
            <span>{'    "}'}</span>
            <br></br>
            <span>{'}'}</span>
        </Snippet>
    )
}

function PHPInstallSnippet() {
    return (
        <Snippet>
            <span>{'php composer.phar install'}</span>
        </Snippet>
    )
}

function PHPSetupSnippet({ user }) {
    let url = window.location.origin
    return (
        <Snippet>
            <span>{"PostHog::init('" + user.team.api_token + "',"}</span>
            <br></br>
            <span>{"    array('host' => '" + url + "')"}</span>
            <br></br>
            <span>{');'}</span>
        </Snippet>
    )
}

function PHPCaptureSnippet() {
    return (
        <Snippet>
            <span>{"PostHog::capture(array(\n    'distinctId' => 'test-user',\n    'event' => 'test-event'\n));"}</span>
        </Snippet>
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
