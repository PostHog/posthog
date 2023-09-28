import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

function NodeInstallSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Bash}>
            {`npm install posthog-node
# OR
yarn add posthog-node
# OR
pnpm add posthog-node`}
        </CodeSnippet>
    )
}

function NodeSetupSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <CodeSnippet language={Language.JavaScript}>
            {`import { PostHog } from 'posthog-node'

const client = new PostHog(
    '${currentTeam?.api_token}',
    { host: '${window.location.origin}' }
)`}
        </CodeSnippet>
    )
}

function NodeCaptureSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript}>
            {`client.capture({
    distinctId: 'test-id',
    event: 'test-event'
})

// Send queued events immediately. Use for example in a serverless environment
// where the program may terminate before everything is sent
client.flush()`}
        </CodeSnippet>
    )
}

export function ProductAnalyticsNodeInstructions(): JSX.Element {
    return (
        <>
            <h3>Install</h3>
            <NodeInstallSnippet />
            <h3>Configure</h3>
            <NodeSetupSnippet />
            <h3>Send an Event</h3>
            <NodeCaptureSnippet />
        </>
    )
}
