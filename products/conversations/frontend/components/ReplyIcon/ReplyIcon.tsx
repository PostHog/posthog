import { IconLock, IconSend } from '@posthog/icons'

import type { TicketChannel } from '../../types'
import { channelIcon } from '../Channels/ChannelsTag'

export function ReplyIcon({ isPrivate, channel }: { isPrivate: boolean; channel?: TicketChannel }): JSX.Element {
    if (isPrivate) {
        return <IconLock />
    }
    return channel ? channelIcon[channel] : <IconSend />
}
