import { IconExternal } from '@posthog/icons'
import { Badge, Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { TicketChannel, TicketChannelDetail } from '../../types'
import { channelIcon, channelTagDetail, channelTagTooltip } from './ChannelsTag'

interface QuillChannelsTagProps {
    channel: TicketChannel
    detail?: TicketChannelDetail | null
    /** When set, the tag links to the originating thread/message and opens in a new tab. */
    to?: string | null
    /** The connected address an email ticket came in on. Shown as the tag's detail for email. */
    emailTo?: string | null
}

export function QuillChannelsTag({ channel, detail, to, emailTo }: QuillChannelsTagProps): JSX.Element {
    const detailText = channelTagDetail(detail, emailTo)
    const tooltip = channelTagTooltip(channel, detailText, !!to)
    const label = (
        <>
            {channelIcon[channel]}
            <span className="truncate">{detailText ? `${channel} · ${detailText}` : channel}</span>
        </>
    )

    if (to) {
        return (
            <Button
                variant="link-muted"
                size="sm"
                nativeButton={false}
                render={<LinkPrimitive to={to} target="_blank" />}
                tooltip={tooltip}
                className="max-w-60"
            >
                {label}
                <IconExternal />
            </Button>
        )
    }

    const badge = <Badge className="max-w-60">{label}</Badge>
    if (!tooltip) {
        return badge
    }
    return (
        <Tooltip>
            <TooltipTrigger render={badge} />
            <TooltipContent>{tooltip}</TooltipContent>
        </Tooltip>
    )
}
