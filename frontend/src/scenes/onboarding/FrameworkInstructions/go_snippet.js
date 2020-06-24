import React from 'react'
import Snippet from './snippet'

function GoInstallSnippet() {
    return (
        <Snippet>
            <span>{'go get github.com/posthog/posthog-go'}</span>
        </Snippet>
    )
}

function GoSetupSnippet({ user }) {
    let url = window.location.origin
    return (
        <Snippet>
            <span>{'package main'}</span>
            <br></br>
            <span>{'import ('}</span>
            <br></br>
            <span>{'    "os"'}</span>
            <br></br>
            <span>{'    "github.com/posthog/posthog-go"'}</span>
            <br></br>
            <span>{')'}</span>
            <br></br>
            <span>{'func main() {'}</span>
            <br></br>
            <span>
                {'    client := posthog.NewWithConfig(os.Getenv("' +
                    user.team.api_token +
                    '\'"), posthog.Config{Endpoint: "' +
                    url +
                    '"})'}
            </span>
            <br></br>
            <span>{'    defer client.Close()'}</span>
            <br></br>
            <span>{'}'}</span>
            <br></br>
        </Snippet>
    )
}

function GoCaptureSnippet() {
    return (
        <Snippet>
            <span>
                {'client.Enqueue(posthog.Capture{\n\tDistinctId: "test-user",\n\tEvent:      "test-snippet"\n})'}
            </span>
        </Snippet>
    )
}

export function GoInstructions({ user }) {
    return (
        <>
            <h3>Install</h3>
            <GoInstallSnippet></GoInstallSnippet>
            <h3>Configure</h3>
            <GoSetupSnippet user={user}></GoSetupSnippet>
            <h3>Send an Event</h3>
            <GoCaptureSnippet></GoCaptureSnippet>
        </>
    )
}
