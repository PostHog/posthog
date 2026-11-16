import { useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

const KEY_PLACEHOLDER = '<your project secret API key>'

export function agentMcpConfig(projectId: number | null): string {
    return JSON.stringify(
        {
            mcpServers: {
                'business-knowledge': {
                    url: `https://mcp.posthog.com/mcp?project_id=${projectId ?? '<project ID>'}`,
                    headers: { Authorization: `Bearer ${KEY_PLACEHOLDER}` },
                },
            },
        },
        null,
        2
    )
}

export function ConnectAgentSetting(): JSX.Element {
    const { currentProjectId } = useValues(projectLogic)

    return (
        <div className="flex flex-col gap-3 max-w-xl">
            <ol className="m-0 pl-5 flex flex-col gap-2 list-decimal">
                <li>
                    <Link
                        to={urls.settings('environment-secret-api-keys')}
                        data-attr="business-knowledge-connect-agent-create-key"
                    >
                        Create a project secret API key
                    </Link>{' '}
                    with the <code>business_knowledge:read</code> scope.
                </li>
                <li>
                    Add the PostHog MCP server to your agent, and replace the placeholder with the key. Most agents
                    accept this format:
                </li>
            </ol>
            <CodeSnippet
                language={Language.JSON}
                thing="agent configuration"
                // pinned: analytics event name. Renaming it breaks insights built on it.
                onCopy={() => posthog.capture('business knowledge agent config copied')}
            >
                {agentMcpConfig(currentProjectId)}
            </CodeSnippet>
            <p className="m-0 text-secondary">
                The agent gets tools to search your sources, read around a result, list libraries, and search and read
                your selected repositories. It cannot change anything, and it cannot read other PostHog data.
            </p>
            <LemonBanner type="warning">
                Keep the key on your server. Anyone who has it can read all the business knowledge in this project, so
                do not put it in a website or a mobile app.
            </LemonBanner>
        </div>
    )
}
