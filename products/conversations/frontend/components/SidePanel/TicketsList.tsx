import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconChevronRight } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonTag, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { ConversationTicket } from '../../types'
import { sidepanelTicketsLogic } from './sidepanelTicketsLogic'

export function TicketsList(): JSX.Element {
    const { tickets, ticketsLoading } = useValues(sidepanelTicketsLogic)
    const { setCurrentTicket, setView } = useActions(sidepanelTicketsLogic)

    if (!posthog.conversations || !posthog.conversations.isAvailable()) {
        return (
            <div className="text-center text-muted-alt py-8">
                <p>Conversations are not available for this team.</p>
            </div>
        )
    }

    if (ticketsLoading) {
        return (
            <div className="flex items-center justify-center h-40">
                <Spinner />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <LemonButton
                type="primary"
                fullWidth
                center
                onClick={() => setView('new')}
                data-attr="sidebar-create-new-ticket"
            >
                Create new ticket
            </LemonButton>

            {tickets.length === 0 ? (
                <div className="text-center text-muted-alt py-8">
                    <p>No tickets yet.</p>
                    <p className="text-sm">Create a new ticket to get help from our team.</p>
                </div>
            ) : (
                <div className="flex flex-col gap-1 mt-2">
                    {tickets.map((ticket: ConversationTicket) => (
                        <div
                            key={ticket.id}
                            className={`flex items-center justify-between p-3 rounded border cursor-pointer hover:bg-surface-light transition-colors ${
                                (ticket.unread_count ?? 0) > 0 ? 'bg-primary-alt-highlight' : 'bg-white'
                            }`}
                            onClick={() => {
                                setCurrentTicket(ticket)
                            }}
                        >
                            <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 mb-1">
                                    <LemonTag
                                        type={
                                            ticket.status === 'resolved'
                                                ? 'success'
                                                : ticket.status === 'new'
                                                  ? 'primary'
                                                  : 'default'
                                        }
                                        size="small"
                                    >
                                        {ticket.status === 'on_hold' ? 'On hold' : ticket.status}
                                    </LemonTag>
                                    {(ticket.unread_count ?? 0) > 0 && (
                                        <LemonBadge.Number
                                            count={ticket.unread_count ?? 0}
                                            size="small"
                                            status="primary"
                                        />
                                    )}
                                </div>
                                {ticket.last_message && (
                                    <p className="text-sm text-primary truncate m-0">{ticket.last_message}</p>
                                )}
                                <p className="text-xs text-muted-alt m-0 mt-1">
                                    <TZLabel time={ticket.created_at} />
                                </p>
                            </div>
                            <IconChevronRight className="text-muted-alt" />
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
