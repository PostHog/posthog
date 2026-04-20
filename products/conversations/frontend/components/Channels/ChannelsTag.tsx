import { IconComment, IconLetter } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { IconSlack } from 'lib/lemon-ui/icons'

import type { TicketChannel, TicketChannelDetail } from '../../types'

const channelIcon: Record<TicketChannel, JSX.Element> = {
    widget: <IconComment />,
    slack: <IconSlack />,
    email: <IconLetter />,
}

const channelDetailLabel: Record<TicketChannelDetail, string> = {
    slack_channel_message: 'Channel message',
    slack_bot_mention: 'Bot mention',
    slack_emoji_reaction: 'Emoji reaction',
    widget_embedded: 'Widget',
    widget_api: 'API',
}

interface ChannelsTagProps {
    channel: TicketChannel
    detail?: TicketChannelDetail | null
}

export function ChannelsTag({ channel, detail }: ChannelsTagProps): JSX.Element {
    const detailText = detail ? channelDetailLabel[detail] : undefined
    const tag = (
        <div className="flex items-center gap-1 text-muted-alt text-xs">
            <LemonTag type="muted">
                <span className="mr-1">{channelIcon[channel]}</span>
                {channel}
                {detailText ? <span className="text-muted-alt ml-0.5">· {detailText}</span> : null}
            </LemonTag>
        </div>
    )
    return detailText ? <Tooltip title={`${channel} · ${detailText}`}>{tag}</Tooltip> : tag
}
