import { Link } from '@posthog/lemon-ui'
import { Button, Text } from '@posthog/quill'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

const MCPServerSettings = (): JSX.Element => {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const codeSnippet = `npx @posthog/wizard mcp add`

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <Text size="xs" render={<p className="m-0" />}>
                    MCP servers allow AI assistants to connect directly to your PostHog instance, enabling them to
                    retrieve insights and perform actions on your behalf.
                </Text>
                <Text size="xs" render={<p className="m-0" />}>
                    You can install the PostHog MCP server in Cursor, Claude Code, Claude Desktop, VS Code, and Zed by
                    running the following command:
                </Text>
                <CodeSnippet language={Language.Bash}>{codeSnippet}</CodeSnippet>
                <Text size="xs" render={<p className="m-0" />}>
                    You can learn more about what tools are available and other installation options{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to="https://posthog.com/docs/model-context-protocol" target="_blank" />}
                    >
                        here
                    </Button>
                </Text>
            </div>
        )
    }

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
