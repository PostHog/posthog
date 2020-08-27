import React from 'react'
import { CodeSnippet } from './CodeSnippet'

function RubyInstallSnippet() {
    return <CodeSnippet language="bash">{'gem "posthog-ruby"'}</CodeSnippet>
}

function RubySetupSnippet({ user }) {
    return (
        <CodeSnippet language="ruby">
            {`posthog = PostHog::Client.new({
    api_key: "${user.team.api_token}",
    api_host: "${window.location.origin}",
    on_error: Proc.new { |status, msg| print msg }
})`}
        </CodeSnippet>
    )
}

function RubyCaptureSnippet() {
    return (
        <CodeSnippet language="ruby">
            {"posthog.capture({\n    distinct_id: 'test-id',\n    event: 'test-event'})"}
        </CodeSnippet>
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
