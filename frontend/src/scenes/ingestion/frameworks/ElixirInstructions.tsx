import React from 'react'
import { CodeSnippet, Language } from './CodeSnippet'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

function ElixirInstallSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Elixir}>
            {'def deps do\n    [\n        {:posthog, "~> 0.1"}\n    ]\nend'}
        </CodeSnippet>
    )
}

function ElixirSetupSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const url = window.location.origin

    return (
        <CodeSnippet language={Language.Elixir}>
            {'config :posthog,\n    api_url: "' + url + '",\n    api_key: "' + currentTeam?.api_token + '"'}
        </CodeSnippet>
    )
}

export function ElixirInstructions(): JSX.Element {
    return (
        <>
            <h3>Install</h3>
            <ElixirInstallSnippet />
            <h3>Configure</h3>
            <ElixirSetupSnippet />
        </>
    )
}
