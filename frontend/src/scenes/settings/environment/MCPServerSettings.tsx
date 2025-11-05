import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

const MCPServerSettings = (): JSX.Element => {
    const codeSnippet = `npx @posthog/wizard mcp add`

    return (
        <div>
            <p className="pb-2">
                MCP servers allow AI assistants to connect directly to your PostHog instance, enabling them to retrieve
                insights and perform actions on your behalf.
            </p>
            <p>
                You can install the PostHog MCP server in Cursor, Claude Code, Claude Desktop, VS Code, and Zed by
                running the following command:
            </p>
            <div className="pb-2">
                <CodeSnippet language={Language.Bash}>{codeSnippet}</CodeSnippet>
            </div>
            <p>
                You can learn more about what tools are available and other installation options{' '}
                <Link to="https://posthog.com/docs/model-context-protocol" target="_blank">
                    here
                </Link>
            </p>
        </div>
    )
}

export default MCPServerSettings
