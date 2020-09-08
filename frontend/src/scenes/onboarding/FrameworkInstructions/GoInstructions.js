import React from 'react'
import { CodeSnippet } from './CodeSnippet'

function GoInstallSnippet() {
    return <CodeSnippet language="bash">{'go get "github.com/posthog/posthog-go"'}</CodeSnippet>
}

function GoSetupSnippet({ user }) {
    return (
        <CodeSnippet language="go">
            {`package main
import (
    "os"
    "github.com/posthog/posthog-go"
)
func main() {
    client := posthog.NewWithConfig(os.Getenv("${user.team.api_token}"), posthog.Config{Endpoint: "${window.location.origin}"})
    defer client.Close()
}`}
        </CodeSnippet>
    )
}

function GoCaptureSnippet() {
    return (
        <CodeSnippet language="go">
            {'client.Enqueue(posthog.Capture{\n    DistinctId: "test-user",\n    Event: "test-snippet"\n})'}
        </CodeSnippet>
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
