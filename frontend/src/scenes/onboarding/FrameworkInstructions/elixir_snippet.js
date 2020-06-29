import React from 'react'
import Snippet from './snippet'

function ElixirInstallSnippet() {
    return (
        <Snippet>
            <span>{'def deps do\n    [\n        {:posthog, "~> 0.1"}\n    ]\nend'}</span>
        </Snippet>
    )
}

function ElixirSetupSnippet({ user }) {
    let url = window.location.origin
    return (
        <Snippet>
            <span>{'config :posthog,\n    api_url: "' + url + '",\n    api_key: "' + user.team.api_token + '"'}</span>
        </Snippet>
    )
}

export function ElixirInstructions({ user }) {
    return (
        <>
            <h3>Install</h3>
            <ElixirInstallSnippet></ElixirInstallSnippet>
            <h3>Configure</h3>
            <ElixirSetupSnippet user={user}></ElixirSetupSnippet>
        </>
    )
}
