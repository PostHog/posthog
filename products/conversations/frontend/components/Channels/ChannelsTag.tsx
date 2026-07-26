import { IconComment, IconExternal, IconGithub, IconLetter } from '@posthog/icons'
import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { IconMicrosoftTeams, IconSlack } from 'lib/lemon-ui/icons'

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
}

export function ChannelsTag({ channel, detail, to }: ChannelsTagProps): JSX.Element {
    const detailText = detail ? channelDetailLabel[detail] : undefined
    const tag = (
        <div className="flex items-center gap-1 text-muted-alt text-xs">
            <LemonTag type="muted">
                <span className="mr-1">{channelIcon[channel]}</span>
                {channel}
                {detailText ? <span className="text-muted-alt ml-0.5">· {detailText}</span> : null}
                {to ? <IconExternal className="ml-1" /> : null}
            </LemonTag>
        </div>
    )

    if (to) {
        const tooltip = channelOpenLabel[channel] ?? `${channel}${detailText ? ` · ${detailText}` : ''}`
        return (
            <Tooltip title={tooltip}>
                {/* Stop propagation so clicking the tag opens Slack without triggering a row/parent click. */}
                <Link to={to} target="_blank" onClick={(e) => e.stopPropagation()}>
                    {tag}
                </Link>
            </Tooltip>
        )
    }

    return detailText ? <Tooltip title={`${channel} · ${detailText}`}>{tag}</Tooltip> : tag
}
