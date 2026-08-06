import { useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

function ElixirInstallSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Elixir}>
            {'def deps do\n    [\n        {:posthog, "~> 1.1.0"}\n    ]\nend'}
        </CodeSnippet>
    )
}

function ElixirSetupSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const url = apiHostOrigin()

    return (
        <CodeSnippet language={Language.Elixir}>
            {'config :posthog,\n    api_url: "' + url + '",\n    api_key: "' + currentTeam?.api_token + '"'}
        </CodeSnippet>
    )
}

export function SDKInstallElixirInstructions(): JSX.Element {
    return (
        <>
            <h3>Install</h3>
            <ElixirInstallSnippet />
            <h3>Configure</h3>
            <ElixirSetupSnippet />
        </>
    )
}
