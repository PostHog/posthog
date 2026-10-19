import posthog from 'posthog-js'

import { Button, Card, CardDescription, CardFooter, CardHeader, CardTitle } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

export function WarehouseMcpSetup(): JSX.Element {
    return (
        <Card size="sm">
            <CardHeader>
                <CardTitle>Continue setting up with the MCP</CardTitle>
                <CardDescription>
                    Ask the PostHog MCP to connect a source, write the SQL that joins it to your PostHog data, and save
                    the result as a view or an insight.
                </CardDescription>
            </CardHeader>
            <CardFooter className="flex-wrap gap-2">
                <Button
                    size="sm"
                    variant="primary"
                    nativeButton={false}
                    render={<LinkPrimitive to={urls.settings('posthog-mcp')} />}
                    data-attr="warehouse-home-mcp-setup"
                    onClick={() => posthog.capture('warehouse getting started clicked', { target: 'mcp_setup' })}
                >
                    Set up the MCP server
                </Button>
                <Button
                    size="sm"
                    nativeButton={false}
                    render={<LinkPrimitive to="https://posthog.com/docs/model-context-protocol" target="_blank" />}
                    data-attr="warehouse-home-mcp-docs"
                    onClick={() => posthog.capture('warehouse getting started clicked', { target: 'mcp_docs' })}
                >
                    Read the MCP docs
                </Button>
            </CardFooter>
        </Card>
    )
}
