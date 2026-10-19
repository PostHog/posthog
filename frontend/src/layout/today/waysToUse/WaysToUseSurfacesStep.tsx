import { useValues } from 'kea'

import { IconMCP } from '@posthog/icons'
import { Badge } from '@posthog/quill'

import { Logomark } from 'lib/brand'
import { IconSlack } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { McpIllustration } from './illustrations/McpIllustration'
import { SlackIllustration } from './illustrations/SlackIllustration'
import { WebAppIllustration } from './illustrations/WebAppIllustration'
import { SLACK_DOCS_URL, WaysToUseSlackState } from './waysToUse'
import { waysToUseLogic } from './waysToUseLogic'
import { WaysToUseSurfaceCard } from './WaysToUseSurfaceCard'
import { WaysToUseSurfaceLink } from './WaysToUseSurfaceLink'

const SLACK_COPY: Record<WaysToUseSlackState, { description: string; label: string; to: string; external: boolean }> = {
    connected: {
        description: 'Your team is connected. Mention @PostHog with a data question, quick fix, or chore.',
        label: 'Open Slack',
        to: 'https://app.slack.com/client',
        external: true,
    },
    can_connect: {
        description: 'Mention @PostHog with a data question, quick fix, or chore.',
        label: 'Connect Slack',
        to: urls.settings('environment-integrations'),
        external: false,
    },
    ask_admin: {
        description: 'Mention @PostHog with a data question, quick fix, or chore. An admin connects it for the team.',
        label: 'How it works',
        to: SLACK_DOCS_URL,
        external: true,
    },
}

export function WaysToUseSurfacesStep(): JSX.Element {
    const { slackState } = useValues(waysToUseLogic)
    const slack = SLACK_COPY[slackState]

    return (
        <div className="@container">
            <div className="grid grid-cols-1 gap-x-4 gap-y-8 @3xl:grid-cols-3">
                <WaysToUseSurfaceCard
                    logo={<Logomark size="xs" />}
                    title="In the web app"
                    description="See what changed today, ask PostHog AI, and open any product."
                    illustration={<WebAppIllustration />}
                    action={
                        <WaysToUseSurfaceLink surface="chat" to={urls.taskNewSession()}>
                            Start a chat
                        </WaysToUseSurfaceLink>
                    }
                />
                <WaysToUseSurfaceCard
                    logo={<IconSlack className="size-5" />}
                    title="In Slack"
                    status={
                        slackState === 'connected' ? (
                            <Badge variant="success" data-attr="today-ways-to-use-slack-connected">
                                Connected
                            </Badge>
                        ) : null
                    }
                    description={slack.description}
                    illustration={<SlackIllustration />}
                    action={
                        <WaysToUseSurfaceLink surface="slack" to={slack.to} external={slack.external}>
                            {slack.label}
                        </WaysToUseSurfaceLink>
                    }
                />
                <WaysToUseSurfaceCard
                    logo={<IconMCP className="size-5" />}
                    title="In your coding agent"
                    description="Plug PostHog into Claude, Cursor, and anything else that speaks MCP."
                    illustration={<McpIllustration />}
                    action={
                        <WaysToUseSurfaceLink surface="mcp" to={urls.settings('posthog-mcp')}>
                            Set up MCP
                        </WaysToUseSurfaceLink>
                    }
                />
            </div>
        </div>
    )
}
