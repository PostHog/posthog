import { IconComment, IconLetter } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { IconSlack } from 'lib/lemon-ui/icons'

import type { TicketChannel } from '../../types'

const channelIcon: Record<TicketChannel, JSX.Element> = {
    widget: <IconComment />,
    slack: <IconSlack />,
    email: <IconLetter />,
}

interface ChannelsTagProps {
    channel: TicketChannel
}

export function ChannelsTag({ channel }: ChannelsTagProps): JSX.Element {
    return (
        <div className="flex items-center gap-1 text-muted-alt text-xs">
            <LemonTag type="muted">
                <span className="mr-1">{channelIcon[channel]}</span>
                {channel}
            </LemonTag>
        </div>
    )
}
