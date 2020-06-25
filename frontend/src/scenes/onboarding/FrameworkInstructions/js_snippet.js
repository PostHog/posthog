import React from 'react'
import Snippet from './snippet'
import '../onboardingWizard.scss'

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
            <h2>Send an Event</h2>
            <p className="prompt-text">
                {"Once you've inserted the snippet, click on a button or form on your website to send an event!"}
            </p>
        </>
    )
}
