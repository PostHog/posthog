import posthog from 'posthog-js'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

const KEY_PLACEHOLDER = '<your project secret API key>'

export function agentMcpConfig(key: string = KEY_PLACEHOLDER): string {
    return JSON.stringify(
        {
            mcpServers: {
                'business-knowledge': {
                    url: 'https://mcp.posthog.com/mcp/business-knowledge',
                    headers: { Authorization: `Bearer ${key}` },
                },
            },
        },
        null,
        2
    )
}

export function onAgentConfigCopied(): void {
    // pinned: analytics event name. Renaming it breaks insights built on it.
    posthog.capture('business knowledge agent config copied')
}

export function AgentConfigSnippet({ apiKey }: { apiKey?: string }): JSX.Element {
    return (
        <CodeSnippet
            language={Language.JSON}
            thing="agent configuration"
            wrap
            // Keeps a newly created key out of session recordings.
            className="ph-no-capture"
            onCopy={onAgentConfigCopied}
        >
            {agentMcpConfig(apiKey)}
        </CodeSnippet>
    )
}
