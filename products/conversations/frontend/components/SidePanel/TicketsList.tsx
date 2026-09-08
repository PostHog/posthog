import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconChevronRight } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonSelect, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { stripMarkdown } from 'lib/utils/markdown'

import {
    type ConversationTicket,
    type SidePanelTicketFilter,
    sidePanelTicketFilterLabels,
    sidePanelTicketFilterOrder,
} from '../../types'
import { sidepanelTicketsLogic } from './sidepanelTicketsLogic'

interface TicketsListProps {
    /** Highlights the matching row in master-detail layouts where the list stays visible */
    selectedTicketId?: string | null
}

export function TicketsList({ selectedTicketId = null }: TicketsListProps): JSX.Element {
    const { tickets, filteredTickets, ticketsLoading, canCreateTicket, effectiveStatusFilter, ticketFilterCounts } =
        useValues(sidepanelTicketsLogic)
    const { setCurrentTicket, setView, setStatusFilter } = useActions(sidepanelTicketsLogic)

    const hasIdentityMode = !!window.JS_POSTHOG_IDENTITY_DISTINCT_ID

    // Unread / Active / All always show so the user can widen the view; a status only earns an
    // entry once there's at least one ticket in it, which keeps the dropdown short.
    const filterOptions = sidePanelTicketFilterOrder
        .filter((filter) => ['unread', 'active', 'all'].includes(filter) || ticketFilterCounts[filter] > 0)
        .map((filter) => ({
            value: filter,
            label: `${sidePanelTicketFilterLabels[filter]} (${ticketFilterCounts[filter]})`,
        }))

    if (!hasIdentityMode && (!posthog.conversations || !posthog.conversations.isAvailable())) {
        return (
            <div className="text-center text-muted-alt py-8">
                <p>Support is not available for this team.</p>
            </div>
        )
    }

    // Polls, tab-focus, and scene remounts all reuse loadTickets. A spinner here once
    // tickets exist would hide the list on every interval.
    if (ticketsLoading && tickets.length === 0) {
        return (
            <div className="flex items-center justify-center h-40">
                <Spinner />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2 h-full min-h-0">
            {canCreateTicket && (
                <LemonButton
                    type="primary"
                    fullWidth
                    center
                    className="shrink-0"
                    onClick={() => setView('new')}
                    data-attr="sidebar-create-new-ticket"
                >
                    Create new ticket
                </LemonButton>
            )}
            {!hasIdentityMode && (
                <p className="text-center text-xs text-muted-alt m-0 shrink-0">
                    Switched browsers?{' '}
                    <Link
                        className="cursor-pointer"
                        onClick={() => setView('restore')}
                        data-attr="sidebar-recover-tickets"
                    >
                        Recover your tickets
                    </Link>
                </p>
            )}
            {tickets.length > 0 && (
                <LemonSelect
                    size="small"
                    fullWidth
                    value={effectiveStatusFilter}
                    onChange={(status: SidePanelTicketFilter | null) => {
                        if (status) {
                            setStatusFilter(status)
                        }
                    }}
                    options={filterOptions}
                    data-attr="sidebar-ticket-status-filter"
                    className="shrink-0"
                />
            )}
            <div className="flex-1 min-h-0 overflow-y-auto">
                {tickets.length === 0 ? (
                    <div className="text-center text-muted-alt py-8">
                        <p>No tickets yet.</p>
                        {canCreateTicket && (
                            <p className="text-sm">Create a new ticket to get help from our support engineers.</p>
                        )}
                    </div>
                ) : filteredTickets.length === 0 ? (
                    <div className="text-center text-muted-alt py-8">
                        {effectiveStatusFilter === 'unread' ? (
                            <>
                                <p>You're all caught up.</p>
                                <Link
                                    className="text-sm"
                                    onClick={() => setStatusFilter('active')}
                                    data-attr="sidebar-ticket-filter-show-active"
                                >
                                    Show active tickets
                                </Link>
                            </>
                        ) : (
                            <>
                                <p>No tickets match this filter.</p>
                                <Link
                                    className="text-sm"
                                    onClick={() => setStatusFilter('all')}
                                    data-attr="sidebar-ticket-filter-show-all"
                                >
                                    Show all tickets
                                </Link>
                            </>
                        )}
                    </div>
                ) : (
                    <div className="flex flex-col gap-1">
                        {filteredTickets.map((ticket: ConversationTicket) => (
                            <div
                                key={ticket.id}
                                className={`flex items-center justify-between p-3 rounded border cursor-pointer hover:bg-surface-light transition-colors ${
                                    (ticket.unread_count ?? 0) > 0 ? 'bg-primary-alt-highlight' : 'bg-surface-primary'
                                } ${ticket.id === selectedTicketId ? 'border-accent' : ''}`}
                                onClick={() => {
                                    setCurrentTicket(ticket)
                                }}
                            >
                                <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-2 mb-1">
                                        {ticket.ticket_number && (
                                            <span className="text-xs font-mono text-muted-alt">
                                                #{ticket.ticket_number}
                                            </span>
                                        )}
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
                                        <p
                                            className={`text-sm text-primary truncate m-0 ${
                                                (ticket.unread_count ?? 0) > 0 ? 'font-semibold' : ''
                                            }`}
                                        >
                                            {stripMarkdown(ticket.last_message)}
                                        </p>
                                    )}
                                    <p className="text-xs text-muted-alt m-0 mt-1">
                                        <TZLabel time={ticket.last_message_at ?? ticket.created_at} />
                                    </p>
                                </div>
                                <IconChevronRight className="text-muted-alt" />
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}
