import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { FlagImplementationSnippet } from './flagImplementationSnippet'
import { SDKKey } from '~/types'

export function NodeInstallSnippet(): JSX.Element {
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

export function NodeSetupSnippet(): JSX.Element {
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

export function ProductAnalyticsNodeInstructions(): JSX.Element {
    return (
        <>
            <h3>Install</h3>
            <NodeInstallSnippet />
            <h3>Configure</h3>
            <NodeSetupSnippet />
            <FlagImplementationSnippet sdkKey={SDKKey.NODE_JS} />
        </>
    )
}
