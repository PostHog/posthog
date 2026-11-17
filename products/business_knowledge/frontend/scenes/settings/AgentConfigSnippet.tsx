import { useValues } from 'kea'
import posthog from 'posthog-js'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { projectLogic } from 'scenes/projectLogic'

const KEY_PLACEHOLDER = '<your project secret API key>'

function agentMcpConfig(projectId: number | null, key: string = KEY_PLACEHOLDER): string {
    return JSON.stringify(
        {
            mcpServers: {
                'business-knowledge': {
                    url: `https://mcp.posthog.com/mcp?project_id=${projectId ?? '<project ID>'}`,
                    headers: { Authorization: `Bearer ${key}` },
                },
            },
        },
        null,
        2
    )
}

export function AgentConfigSnippet({ apiKey }: { apiKey?: string }): JSX.Element {
    const { currentProjectId } = useValues(projectLogic)

    return (
        <CodeSnippet
            language={Language.JSON}
            thing="agent configuration"
            wrap
            // Keeps a newly created key out of session recordings.
            className="ph-no-capture"
            // pinned: analytics event name. Renaming it breaks insights built on it.
            onCopy={() => posthog.capture('business knowledge agent config copied')}
        >
            {agentMcpConfig(currentProjectId, apiKey)}
        </CodeSnippet>
    )
}
