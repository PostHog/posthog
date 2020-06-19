import React from 'react'
import Snippet from './snippet'

function JSInstallSnippet() {
    return (
        <Snippet>
            <span>{'npm install posthog-js'}</span>
            <br></br>
            <span>{'// or'}</span>
            <br></br>
            <span>{'yarn add posthog-js'}</span>
        </Snippet>
    )
}

function JSSetupSnippet({ user }) {
    let url = window.location.origin
    return (
        <Snippet>
            <span>{"import posthog from 'posthog-js';"}</span>
            <br></br>
            <span>{'posthog.init("' + user.team.api_token + '", {api_host: "' + url + '"});'}</span>
        </Snippet>
    )
}

export function JSInstructions({ user }) {
    return (
        <>
            <h3>Install</h3>
            <JSInstallSnippet></JSInstallSnippet>
            <h3>Configure</h3>
            <JSSetupSnippet user={user}></JSSetupSnippet>
        </>
    )
}
