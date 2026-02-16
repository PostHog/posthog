import { LemonCollapse, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { Ticket } from '../../types'

interface PreviousTicketsPanelProps {
    previousTickets: Ticket[]
    previousTicketsLoading?: boolean
}

export function PreviousTicketsPanel({
    previousTickets,
    previousTicketsLoading,
}: PreviousTicketsPanelProps): JSX.Element {
    return (
        <LemonCollapse
            className="bg-surface-primary"
            panels={[
                {
                    key: 'previous-tickets',
                    header: (
                        <>
                            Previous tickets
                            {previousTickets.length > 0 && (
                                <span className="text-muted-alt font-normal ml-1">({previousTickets.length})</span>
                            )}
                        </>
                    ),
                    content: (
                        <div className="space-y-2">
                            {previousTicketsLoading ? (
                                <div className="text-muted-alt text-xs">Loading previous tickets...</div>
                            ) : previousTickets.length === 0 ? (
                                <div className="text-muted-alt text-xs">No previous tickets found</div>
                            ) : (
                                <div className="space-y-2 max-h-96 overflow-auto">
                                    {previousTickets.map((ticket) => (
                                        <Link
                                            key={ticket.id}
                                            to={urls.supportTicketDetail(ticket.id)}
                                            className="block p-2 mb-2 rounded border border-primary hover:bg-accent-3000 transition-colors hover:border-secondary"
                                        >
                                            <div className="flex items-center justify-between mb-1">
                                                <span className="font-mono text-xs text-muted-alt">
                                                    #{ticket.ticket_number}
                                                </span>
                                                <LemonTag
                                                    type={
                                                        ticket.status === 'resolved'
                                                            ? 'success'
                                                            : ticket.status === 'new'
                                                              ? 'primary'
                                                              : 'default'
                                                    }
                                                >
                                                    {ticket.status === 'on_hold' ? 'On hold' : ticket.status}
                                                </LemonTag>
                                            </div>
                                            {ticket.last_message_text && (
                                                <div className="text-xs text-muted truncate mb-1">
                                                    {ticket.last_message_text}
                                                </div>
                                            )}
                                            <div className="text-xs text-muted-alt">
                                                Created <TZLabel time={ticket.created_at} />
                                            </div>
                                        </Link>
                                    ))}
                                </div>
                            )}
                        </div>
                    ),
                },
            ]}
        />
    )
}
