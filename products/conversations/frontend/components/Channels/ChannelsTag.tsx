import { IconComment, IconExternal, IconGithub, IconLetter } from '@posthog/icons'

import { IconMicrosoftTeams, IconSlack } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { Badge, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'

import type { Ticket, TicketChannel, TicketChannelDetail } from '../../types'

// Builds a deep link to the originating Slack thread so the Channel tag can be clickable.
export function getChannelThreadUrl(ticket: Ticket | null): string | undefined {
    if (ticket?.channel_source === 'slack' && ticket.slack_channel_id && ticket.slack_thread_ts) {
        return `https://app.slack.com/archives/${ticket.slack_channel_id}/p${ticket.slack_thread_ts.replace('.', '')}`
    }
    return undefined
}

export const channelIcon: Record<TicketChannel, JSX.Element> = {
    widget: <IconComment />,
    slack: <IconSlack />,
    teams: <IconMicrosoftTeams />,
    email: <IconLetter />,
    github: <IconGithub />,
}

// Channels a team member replies back into externally, branded on the composer
// (placeholder text + send-button logo). Others fall back to the generic composer.
const replyChannelLabel: Partial<Record<TicketChannel, string>> = {
    slack: 'Slack',
    teams: 'Microsoft Teams',
    github: 'GitHub',
}

export function getReplyPlaceholder(channel?: TicketChannel): string {
    const label = channel ? replyChannelLabel[channel] : undefined
    return label ? `Reply in ${label}...` : 'Type your message...'
}

export function hasReplyChannelBranding(channel?: TicketChannel): channel is TicketChannel {
    return !!channel && channel in replyChannelLabel
}

const channelDetailLabel: Record<TicketChannelDetail, string> = {
    slack_channel_message: 'Channel message',
    slack_bot_mention: 'Bot mention',
    slack_emoji_reaction: 'Emoji reaction',
    teams_channel_message: 'Teams channel message',
    teams_bot_mention: 'Teams bot mention',
    widget_embedded: 'Widget',
    widget_api: 'API',
    github_issue: 'GitHub issue',
}

const channelOpenLabel: Partial<Record<TicketChannel, string>> = {
    slack: 'Open in Slack',
}

interface ChannelsTagProps {
    channel: TicketChannel
    detail?: TicketChannelDetail | null
    /** When set, the tag links to the originating thread/message and opens in a new tab. */
    to?: string | null
    /** The connected address an email ticket came in on. Shown as the tag's detail for email. */
    emailTo?: string | null
}

export function ChannelsTag({ channel, detail, to, emailTo }: ChannelsTagProps): JSX.Element {
    const detailText = detail ? channelDetailLabel[detail] : (emailTo ?? undefined)
    const tag = (
        <Badge
            variant="default"
            render={
                to ? (
                    // Stop propagation so clicking the tag opens Slack without triggering a row/parent click.
                    <LinkPrimitive to={to} target="_blank" onClick={(e) => e.stopPropagation()} />
                ) : undefined
            }
        >
            {channelIcon[channel]}
            {channel}
            {detailText ? <span className="text-muted-alt">· {detailText}</span> : null}
            {to ? <IconExternal /> : null}
        </Badge>
    )

    if (to) {
        const tooltip = channelOpenLabel[channel] ?? `${channel}${detailText ? ` · ${detailText}` : ''}`
        return (
            <Tooltip>
                <TooltipTrigger render={tag} />
                <TooltipContent>{tooltip}</TooltipContent>
            </Tooltip>
        )
    }

    return detailText ? (
        <Tooltip>
            <TooltipTrigger render={tag} />
            <TooltipContent>
                {channel} · {detailText}
            </TooltipContent>
        </Tooltip>
    ) : (
        tag
    )
}
