import React from 'react'
import { CodeSnippet, Language } from './CodeSnippet'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

function RubyInstallSnippet(): JSX.Element {
    return <CodeSnippet language={Language.Bash}>{'gem "posthog-ruby"'}</CodeSnippet>
}

function RubySetupSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <CodeSnippet language={Language.Ruby}>
            {`posthog = PostHog::Client.new({
    api_key: "${currentTeam?.api_token}",
    api_host: "${window.location.origin}",
    on_error: Proc.new { |status, msg| print msg }
})`}
        </CodeSnippet>
    )
}

function RubyCaptureSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Ruby}>
            {"posthog.capture({\n    distinct_id: 'test-id',\n    event: 'test-event'})"}
        </CodeSnippet>
    )
}

export function RubyInstructions(): JSX.Element {
    return (
        <>
            <h3>Install</h3>
            <RubyInstallSnippet />
            <h3>Configure</h3>
            <RubySetupSnippet />
            <h3>Send an Event</h3>
            <RubyCaptureSnippet />
        </>
    )
}
