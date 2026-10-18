import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconSupport } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyDescription,
    EmptyHeader,
    IconStack,
    IconStackItem,
    EmptyTitle,
    CardGroup,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Text,
} from '@posthog/quill'

import {
    type ConversationTicket,
    type SidePanelTicketFilter,
    sidePanelTicketFilterLabels,
    sidePanelTicketFilterOrder,
} from '../../types'
import { sidepanelTicketsLogic } from '../SidePanel/sidepanelTicketsLogic'
import { QuillTicketRow } from './QuillTicketRow'

export function QuillTicketsList(): JSX.Element {
    const { tickets, filteredTickets, ticketsLoading, canCreateTicket, effectiveStatusFilter, ticketFilterCounts } =
        useValues(sidepanelTicketsLogic)
    const { setCurrentTicket, setView, setStatusFilter } = useActions(sidepanelTicketsLogic)

    const hasIdentityMode = !!window.JS_POSTHOG_IDENTITY_DISTINCT_ID

    if (!hasIdentityMode && (!posthog.conversations || !posthog.conversations.isAvailable())) {
        return (
            <Empty>
                <EmptyHeader>
                    <IconStack>
                        <IconStackItem color="var(--color-product-support-light)">
                            <IconSupport />
                        </IconStackItem>
                    </IconStack>
                    <EmptyTitle>Support chat isn't available right now</EmptyTitle>
                    <EmptyDescription>
                        An ad blocker or network policy can stop it from loading. You can still ask PostHog AI or the
                        community.
                    </EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    // Polls, tab focus and remounts all reload the tickets, so the placeholder only shows before the first load.
    if (ticketsLoading && tickets.length === 0) {
        return (
            <div className="flex flex-col gap-2">
                <Skeleton className="h-14" />
                <Skeleton className="h-14 opacity-80" />
            </div>
        )
    }

    // Unread, active and all always show so the user can widen the view. A status shows once it has a ticket, and
    // the selected one stays even when its count drops to zero.
    const filters = sidePanelTicketFilterOrder.filter(
        (filter) =>
            ['unread', 'active', 'all'].includes(filter) ||
            ticketFilterCounts[filter] > 0 ||
            filter === effectiveStatusFilter
    )
    const filterLabel = (filter: SidePanelTicketFilter): string =>
        `${sidePanelTicketFilterLabels[filter]} (${ticketFilterCounts[filter]})`

    return (
        <div className="flex flex-col gap-3">
            {canCreateTicket && (
                <Button variant="primary" onClick={() => setView('new')} data-attr="sidebar-create-new-ticket">
                    Create new ticket
                </Button>
            )}
            {!hasIdentityMode && (
                <Text size="xs" variant="muted" className="text-center">
                    Switched browsers?{' '}
                    <Button
                        variant="link"
                        size="inline"
                        onClick={() => setView('restore')}
                        data-attr="sidebar-recover-tickets"
                    >
                        Recover your tickets
                    </Button>
                </Text>
            )}
            {tickets.length > 0 && (
                <Select
                    value={effectiveStatusFilter}
                    onValueChange={(filter) => filter && setStatusFilter(filter as SidePanelTicketFilter)}
                >
                    <SelectTrigger aria-label="Filter tickets" data-attr="sidebar-ticket-status-filter">
                        <SelectValue>{(filter: SidePanelTicketFilter) => filterLabel(filter)}</SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                        {filters.map((filter) => (
                            <SelectItem key={filter} value={filter}>
                                {filterLabel(filter)}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            )}
            {tickets.length === 0 ? (
                <Text size="xs" variant="muted" className="py-4 text-center">
                    {canCreateTicket
                        ? 'No tickets yet. Create one to get help from our support engineers.'
                        : 'No tickets yet.'}
                </Text>
            ) : filteredTickets.length === 0 ? (
                <div className="flex flex-col items-center gap-1 py-4">
                    <Text size="xs" variant="muted">
                        {effectiveStatusFilter === 'unread' ? "You're all caught up." : 'No tickets match this filter.'}
                    </Text>
                    <Button
                        variant="link"
                        size="sm"
                        onClick={() => setStatusFilter(effectiveStatusFilter === 'unread' ? 'active' : 'all')}
                        data-attr={
                            effectiveStatusFilter === 'unread'
                                ? 'sidebar-ticket-filter-show-active'
                                : 'sidebar-ticket-filter-show-all'
                        }
                    >
                        {effectiveStatusFilter === 'unread' ? 'Show active tickets' : 'Show all tickets'}
                    </Button>
                </div>
            ) : (
                <CardGroup>
                    {filteredTickets.map((ticket: ConversationTicket) => (
                        <QuillTicketRow key={ticket.id} ticket={ticket} onOpen={() => setCurrentTicket(ticket)} />
                    ))}
                </CardGroup>
            )}
        </div>
    )
}
