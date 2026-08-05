import { LemonCard, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { ChannelsTag, getChannelThreadUrl } from '../../components/Channels/ChannelsTag'
import type { Ticket } from '../../types'

function customerName(ticket: Ticket): string {
    return (
        ticket.person?.properties?.name ||
        ticket.person?.properties?.email ||
        ticket.anonymous_traits?.name ||
        ticket.anonymous_traits?.email ||
        ticket.email_from ||
        ticket.distinct_id ||
        'Unknown customer'
    )
}

/** Compact info panel for a merged ticket, shown in the master's sidebar while that ticket's
 * messages are interleaved. Color-coded to match its conversation pills. */
export function MergedTicketInfoCard({ ticket, color }: { ticket: Ticket; color?: string }): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="p-3">
            <div className="flex items-center gap-2 mb-2">
                <span className="block w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
                <h3 className="text-sm font-semibold flex-1 leading-none">Merged ticket #{ticket.ticket_number}</h3>
                <LemonTag type="muted" className="capitalize">
                    {ticket.status}
                </LemonTag>
            </div>
            <div className="space-y-2 text-xs">
                <div className="flex justify-between items-start gap-2">
                    <span className="text-muted-alt shrink-0">Customer</span>
                    <span className="truncate text-right" title={customerName(ticket)}>
                        {customerName(ticket)}
                    </span>
                </div>
                <div className="flex justify-between items-center">
                    <span className="text-muted-alt">Channel</span>
                    <span className="capitalize">
                        <ChannelsTag
                            channel={ticket.channel_source}
                            detail={ticket.channel_detail}
                            to={getChannelThreadUrl(ticket)}
                        />
                    </span>
                </div>
                {ticket.channel_source === 'email' && ticket.email_subject && (
                    <div className="flex justify-between items-start gap-2">
                        <span className="text-muted-alt shrink-0">Subject</span>
                        <span className="truncate text-right" title={ticket.email_subject}>
                            {ticket.email_subject}
                        </span>
                    </div>
                )}
                {ticket.created_at && (
                    <div className="flex justify-between">
                        <span className="text-muted-alt">Created</span>
                        <span>
                            <TZLabel time={ticket.created_at} />
                        </span>
                    </div>
                )}
                {ticket.updated_at && (
                    <div className="flex justify-between">
                        <span className="text-muted-alt">Updated</span>
                        <span>
                            <TZLabel time={ticket.updated_at} />
                        </span>
                    </div>
                )}
            </div>
        </LemonCard>
    )
}
