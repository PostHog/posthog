import { IconMCP } from '@posthog/icons'

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
            <div className="grid grid-cols-1 gap-x-4 gap-y-8 @3xl:grid-cols-3">
                <WaysToUseSurfaceCard
                    order={0}
                    logo={<Logomark size="xs" />}
                    title="In the web app"
                    description="See what changed today, ask PostHog AI, and open any product."
                    illustration={<WebAppIllustration />}
                    action={
                        <WaysToUseSurfaceLink surface="chat" to={urls.taskNewSession()} onClick={onSurfaceLinkClick}>
                            Start a chat
                        </WaysToUseSurfaceLink>
                    }
                />
                <WaysToUseSurfaceCard
                    order={1}
                    logo={<IconSlack className="size-5" />}
                    title="In Slack"
                    description="Mention @PostHog with a data question, quick fix, or chore."
                    illustration={<SlackIllustration />}
                    action={
                        <WaysToUseSurfaceLink
                            surface="slack"
                            to={urls.settings('environment-integrations')}
                            onClick={onSurfaceLinkClick}
                        >
                            Connect Slack
                        </WaysToUseSurfaceLink>
                    }
                />
                <WaysToUseSurfaceCard
                    order={2}
                    logo={<IconMCP className="size-5" />}
                    title="In your coding agent"
                    description="Plug PostHog into Claude, Cursor, and anything else that speaks MCP."
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
