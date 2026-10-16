import { IconMCP } from '@posthog/icons'
import { Badge, Dot } from '@posthog/quill'

import { Logomark } from 'lib/brand'
import { IconSlack } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { McpIllustration } from './illustrations/McpIllustration'
import { SlackIllustration } from './illustrations/SlackIllustration'
import { WebAppIllustration } from './illustrations/WebAppIllustration'
import { WaysToUseSurface } from './waysToUse'
import { WaysToUseSurfaceCard } from './WaysToUseSurfaceCard'
import { WaysToUseSurfaceLink } from './WaysToUseSurfaceLink'

export interface WaysToUseSurfacesProps {
    onSurfaceLinkClick: (surface: WaysToUseSurface) => void
}

export function WaysToUseSurfaces({ onSurfaceLinkClick }: WaysToUseSurfacesProps): JSX.Element {
    return (
        <div className="@container">
            <div className="grid grid-cols-1 gap-x-4 gap-y-8 @2xl:grid-cols-3">
                <WaysToUseSurfaceCard
                    order={0}
                    logo={<Logomark size="xs" />}
                    title="Web app"
                    description="See what changed today, chat with PostHog AI, and open any product."
                    illustration={<WebAppIllustration />}
                    action={
                        <Badge>
                            <Dot variant="success" pulse />
                            You are here
                        </Badge>
                    }
                />
                <WaysToUseSurfaceCard
                    order={1}
                    logo={<IconSlack className="size-5" />}
                    title="Slack"
                    description="Tag @PostHog in any thread to ask about your data."
                    illustration={<SlackIllustration />}
                    action={
                        <WaysToUseSurfaceLink
                            surface="slack"
                            to={urls.settings('environment-integrations', 'integration-slack')}
                            onClick={onSurfaceLinkClick}
                        >
                            Connect Slack
                        </WaysToUseSurfaceLink>
                    }
                />
                <WaysToUseSurfaceCard
                    order={2}
                    logo={<IconMCP className="size-5" />}
                    title="MCP"
                    description="Use PostHog data and tools in Claude, Cursor, and other AI agents."
                    illustration={<McpIllustration />}
                    action={
                        <WaysToUseSurfaceLink
                            surface="mcp"
                            to={urls.settings('posthog-mcp')}
                            onClick={onSurfaceLinkClick}
                        >
                            Set up MCP
                        </WaysToUseSurfaceLink>
                    }
                />
            </div>
        </div>
    )
}
