import React from 'react'

export function NodeInstallSnippet() {
    return (
        <div className="code-container">
            <pre className="code scrolling-code">
                <span>{'npm install posthog-node'}</span>
                <br></br>
                <span>{'// or'}</span>
                <br></br>
                <span>{'yarn add posthog-node'}</span>
            </pre>
        </div>
    )
}

export function NodeSetupSnippet({ user }) {
    let url = window.location.origin
    return (
        <div className="code-container">
            <pre className="code scrolling-code">
                <span>{"import PostHog from 'posthog-node'"}</span>
                <br></br>
                <span>{'const client = new PostHog('}</span>
                <br></br>
                <span>{'    ' + user.team.api_token + ','}</span>
                <br></br>
                <span>{'   { host: ' + url + ' }'}</span>
                <br></br>
                <span>{')'}</span>
            </pre>
        </div>
    )
}
