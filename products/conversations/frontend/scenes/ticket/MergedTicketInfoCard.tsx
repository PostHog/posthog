import { LemonCard, LemonCollapse, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { ChannelsTag, getChannelThreadUrl } from '../../components/Channels/ChannelsTag'
import { type MergedTicketSummary, type Ticket, priorityOptions } from '../../types'

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

function InfoRow({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex justify-between items-start gap-2">
            <span className="text-muted-alt shrink-0">{label}</span>
            <span className="text-right min-w-0">{children}</span>
        </div>
    )
}

/** Compact info panel for a merged ticket, shown in the master's sidebar while that ticket's
 * messages are interleaved. Color-coded to match its conversation pills. Extra fields are
 * collapsed by default. */
export function MergedTicketInfoCard({ ticket, color }: { ticket: Ticket; color?: string }): JSX.Element {
    const subject = ticket.email_subject || ticket.last_message_text
    const priorityLabel = ticket.priority
        ? (priorityOptions.find((o) => o.value === ticket.priority)?.label ?? ticket.priority)
        : 'None'

    return (
        <LemonCard hoverEffect={false} className="p-3">
            <div className="flex items-center justify-between gap-2 mb-2">
                <h3 className="text-sm font-semibold flex items-center gap-2 mb-0">
                    <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
                    Merged ticket #{ticket.ticket_number}
                </h3>
                <LemonTag type="muted" className="capitalize">
                    {ticket.status}
                </LemonTag>
            </div>
            <div className="space-y-2 text-xs">
                <InfoRow label="Customer">
                    <span className="truncate block" title={customerName(ticket)}>
                        {customerName(ticket)}
                    </span>
                </InfoRow>
                {subject && (
                    <InfoRow label="Subject">
                        <span className="truncate block" title={subject}>
                            {subject}
                        </span>
                    </InfoRow>
                )}
                <InfoRow label="Channel">
                    <span className="capitalize">
                        <ChannelsTag
                            channel={ticket.channel_source}
                            detail={ticket.channel_detail}
                            to={getChannelThreadUrl(ticket)}
                        />
                    </span>
                </InfoRow>
            </div>
            <LemonCollapse
                className="mt-2"
                size="small"
                panels={[
                    {
                        key: 'more',
                        header: 'More details',
                        content: (
                            <div className="space-y-2 text-xs">
                                {ticket.created_at && (
                                    <InfoRow label="Created">
                                        <TZLabel time={ticket.created_at} />
                                    </InfoRow>
                                )}
                                {ticket.updated_at && (
                                    <InfoRow label="Updated">
                                        <TZLabel time={ticket.updated_at} />
                                    </InfoRow>
                                )}
                                <InfoRow label="Priority">
                                    <span className="capitalize">{priorityLabel}</span>
                                </InfoRow>
                                <InfoRow label="Tags">
                                    {ticket.tags && ticket.tags.length > 0 ? (
                                        <span className="flex flex-wrap justify-end gap-1">
                                            {ticket.tags.map((tag) => (
                                                <LemonTag key={tag} type="muted">
                                                    {tag}
                                                </LemonTag>
                                            ))}
                                        </span>
                                    ) : (
                                        'None'
                                    )}
                                </InfoRow>
                            </div>
                        ),
                    },
                ]}
            />
        </LemonCard>
    )
}

/** Placeholder shown while a merged ticket's full details + messages are loading. The identity
 * (number, color) is known from the summary, so only the body fields are skeletons. */
export function MergedTicketInfoCardSkeleton({
    ticket,
    color,
}: {
    ticket: MergedTicketSummary
    color?: string
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="p-3">
            <div className="flex items-center justify-between gap-2 mb-2">
                <h3 className="text-sm font-semibold flex items-center gap-2 mb-0">
                    <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
                    Merged ticket #{ticket.ticket_number}
                </h3>
                <LemonSkeleton className="h-4 w-16" />
            </div>
            <div className="space-y-2">
                <LemonSkeleton className="h-3 w-full" />
                <LemonSkeleton className="h-3 w-4/5" />
                <LemonSkeleton className="h-3 w-3/5" />
            </div>
        </LemonCard>
    )
}
