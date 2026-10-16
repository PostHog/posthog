import { IconMCP, IconTerminal } from '@posthog/icons'
import { Badge, Button } from '@posthog/quill'

import { Logomark } from 'lib/brand'
import { IconSlack } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { CliIllustration } from './illustrations/CliIllustration'
import { McpIllustration } from './illustrations/McpIllustration'
import { SlackIllustration } from './illustrations/SlackIllustration'
import { WebAppIllustration } from './illustrations/WebAppIllustration'
import { WaysToUseSurface } from './waysToUse'
import { WaysToUseSurfaceCard } from './WaysToUseSurfaceCard'

export interface WaysToUseSurfacesProps {
    onSurfaceLinkClick: (surface: WaysToUseSurface) => void
}

export function WaysToUseSurfaces({ onSurfaceLinkClick }: WaysToUseSurfacesProps): JSX.Element {
    return (
        <div className="@container">
            <div className="grid grid-cols-1 gap-x-4 gap-y-6 @md:grid-cols-2 @3xl:grid-cols-4">
                <WaysToUseSurfaceCard
                    logo={<Logomark size="xs" />}
                    title="Web app"
                    description="See what changed today, chat with PostHog AI, and open every product."
                    illustration={<WebAppIllustration />}
                    action={<Badge>You are here</Badge>}
                />
                <WaysToUseSurfaceCard
                    logo={<IconSlack className="size-5" />}
                    title="Slack"
                    description="Tag @PostHog in a thread to ask about your data and get the answer there."
                    illustration={<SlackIllustration />}
                    action={
                        <Button
                            size="sm"
                            variant="outline"
                            nativeButton={false}
                            render={
                                <LinkPrimitive
                                    to={urls.settings('environment-integrations', 'integration-slack')}
                                    onClick={() => onSurfaceLinkClick('slack')}
                                />
                            }
                            data-attr="today-ways-to-use-slack"
                        >
                            Connect Slack
                        </Button>
                    }
                />
                <WaysToUseSurfaceCard
                    logo={<IconMCP className="size-5" />}
                    title="MCP"
                    description="Use PostHog tools and data in Claude, Cursor, and other AI agents."
                    illustration={<McpIllustration />}
                    action={
                        <Button
                            size="sm"
                            variant="outline"
                            nativeButton={false}
                            render={
                                <LinkPrimitive
                                    to={urls.settings('posthog-mcp')}
                                    onClick={() => onSurfaceLinkClick('mcp')}
                                />
                            }
                            data-attr="today-ways-to-use-mcp"
                        >
                            Set up MCP
                        </Button>
                    }
                />
                <WaysToUseSurfaceCard
                    logo={<IconTerminal className="size-5" />}
                    title="CLI"
                    description="Call PostHog tools from your terminal, scripts, and coding agents."
                    illustration={<CliIllustration />}
                    action={
                        <Button
                            size="sm"
                            variant="outline"
                            nativeButton={false}
                            render={
                                <LinkPrimitive
                                    to="https://posthog.com/docs/cli"
                                    target="_blank"
                                    onClick={() => onSurfaceLinkClick('cli')}
                                />
                            }
                            data-attr="today-ways-to-use-cli"
                        >
                            Install the CLI
                        </Button>
                    }
                />
            </div>
        </div>
    )
}
