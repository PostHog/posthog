import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

function GoInstallSnippet(): JSX.Element {
    return <CodeSnippet language={Language.Bash}>{'go get "github.com/posthog/posthog-go"'}</CodeSnippet>
}

function GoSetupSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <CodeSnippet language={Language.Go}>
            {`package main
import (
    "github.com/posthog/posthog-go"
)
func main() {
    client, _ := posthog.NewWithConfig("${currentTeam?.api_token}", posthog.Config{Endpoint: "${window.location.origin}"})
    defer client.Close()
}`}
        </CodeSnippet>
    )
}

export function SDKInstallGoInstructions(): JSX.Element {
    return (
        <>
            <h3>Install</h3>
            <GoInstallSnippet />
            <h3>Configure</h3>
            <GoSetupSnippet />
        </>
    )
}
