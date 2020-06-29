import React from 'react'
import Snippet from './snippet'

function RubyInstallSnippet() {
    return (
        <Snippet>
            <span>{'gem "posthog-ruby"'}</span>
        </Snippet>
    )
}

function RubySetupSnippet({ user }) {
    let url = window.location.origin
    return (
        <Snippet>
            <span>{'posthog = PostHog::Client.new({'}</span>
            <br></br>
            <span>{'    api_key: "' + user.team.api_token + '",'}</span>
            <br></br>
            <span>{'    api_host: "' + url + ' ",'}</span>
            <br></br>
            <span>{'    on_error: Proc.new { |status, msg| print msg }'}</span>
            <br></br>
            <span>{'})'}</span>
        </Snippet>
    )
}

function RubyCaptureSnippet() {
    return (
        <Snippet>
            <span>{"posthog.capture({\n    distinct_id: 'test-id',\n    event: 'test-event'})"}</span>
        </Snippet>
    )
}

export function RubyInstructions({ user }) {
    return (
        <>
            <h3>Install</h3>
            <RubyInstallSnippet></RubyInstallSnippet>
            <h3>Configure</h3>
            <RubySetupSnippet user={user}></RubySetupSnippet>
            <h3>Send an Event</h3>
            <RubyCaptureSnippet></RubyCaptureSnippet>
        </>
    )
}
