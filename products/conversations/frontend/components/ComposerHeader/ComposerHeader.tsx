import { Tooltip } from '@posthog/lemon-ui'

import type { TicketChannel } from '../../types'
import { getReplyDestination } from '../Channels/ChannelsTag'
import { ReplyIcon } from '../ReplyIcon/ReplyIcon'

export interface SimplifiedRepliesProps {
    /** Who the reply reaches, e.g. the customer's email address or name */
    recipient?: string | null
    /** The ticket's saved status, e.g. "Open" */
    statusLabel?: string
}

// The editor placeholder names the channel only until the agent starts to type, so the header keeps the destination visible.
export function ComposerHeader({
    isPrivate,
    channel,
    recipient,
    statusLabel,
}: SimplifiedRepliesProps & { isPrivate: boolean; channel?: TicketChannel }): JSX.Element {
    const detail = isPrivate ? 'Only your team will see this' : recipient
    return (
        <div className="flex items-center gap-2 px-2 py-1 text-xs" data-attr="composer-header">
            <span className="flex text-sm">
                <ReplyIcon isPrivate={isPrivate} channel={channel} />
            </span>
            <span className="font-semibold shrink-0">{isPrivate ? 'Private note' : getReplyDestination(channel)}</span>
            {detail ? (
                <Tooltip title={<span className="ph-no-capture">{detail}</span>}>
                    <span className="ph-no-capture truncate text-secondary min-w-0">{detail}</span>
                </Tooltip>
            ) : null}
            {statusLabel ? (
                <span className="ml-auto shrink-0 text-secondary">{`Ticket status: ${statusLabel}`}</span>
            ) : null}
        </div>
    )
}
