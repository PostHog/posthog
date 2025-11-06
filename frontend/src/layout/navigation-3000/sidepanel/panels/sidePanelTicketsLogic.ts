import { actions, afterMount, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { ZendeskTicket } from '~/types'

import type { sidePanelTicketsLogicType } from './sidePanelTicketsLogicType'

export interface SidePanelTicketsLogicProps {
    key?: string
}

export const sidePanelTicketsLogic = kea<sidePanelTicketsLogicType>([
    path(['layout', 'navigation-3000', 'sidepanel', 'panels', 'sidePanelTicketsLogic']),
    props({} as SidePanelTicketsLogicProps),
    key((props) => props.key || 'default'),
    actions({
        setExpandedTicketId: (ticketId: number | null) => ({ ticketId }),
        setStatusFilter: (status: string) => ({ status }),
        setReplyingToTicketId: (ticketId: number | null) => ({ ticketId }),
        setReplySuccessForTicket: (ticketId: number | null) => ({ ticketId }),
    }),
    reducers({
        expandedTicketId: [
            null as number | null,
            {
                setExpandedTicketId: (_, { ticketId }) => ticketId,
            },
        ],
        statusFilter: [
            'open' as string,
            {
                setStatusFilter: (_, { status }) => status,
            },
        ],
        replyingToTicketId: [
            null as number | null,
            {
                setReplyingToTicketId: (_, { ticketId }) => ticketId,
            },
        ],
        replySuccessTicketId: [
            null as number | null,
            {
                setReplySuccessForTicket: (_, { ticketId }) => ticketId,
            },
        ],
    }),
    loaders(({ actions, values }) => ({
        ticketsResponse: [
            { tickets: [], count: 0 } as { tickets: ZendeskTicket[]; count: number; error?: string },
            {
                loadTickets: async () => {
                    try {
                        return await api.users.zendeskTickets()
                    } catch (error) {
                        console.error('Failed to load Zendesk tickets:', error)
                        return { tickets: [], count: 0, error: 'Failed to load tickets' }
                    }
                },
                replyToTicket: async ({ ticketId, body }: { ticketId: number; body: string }) => {
                    try {
                        const result = await api.users.replyToZendeskTicket(ticketId, body)
                        if (result.success) {
                            actions.setReplyingToTicketId(null)
                            actions.setReplySuccessForTicket(ticketId)

                            // Optimistically update the ticket status to 'open' in the UI
                            const updatedTickets = values.ticketsResponse.tickets.map((ticket) =>
                                ticket.id === ticketId ? { ...ticket, status: 'open' } : ticket
                            )

                            // Wait 5 seconds then refresh to get the full updated data
                            setTimeout(() => {
                                actions.loadTickets()
                                actions.setReplySuccessForTicket(null)
                            }, 5000)

                            return { ...values.ticketsResponse, tickets: updatedTickets }
                        }
                        return values.ticketsResponse
                    } catch (error) {
                        console.error('Failed to reply to ticket:', error)
                        throw error
                    }
                },
            },
        ],
    })),
    selectors({
        tickets: [(s) => [s.ticketsResponse], (ticketsResponse) => ticketsResponse.tickets],
        ticketsCount: [(s) => [s.ticketsResponse], (ticketsResponse) => ticketsResponse.count],
        hasError: [(s) => [s.ticketsResponse], (ticketsResponse) => !!ticketsResponse.error],
        hasPendingTickets: [(s) => [s.tickets], (tickets) => tickets.some((ticket) => ticket.status === 'pending')],
    }),
    afterMount(({ actions }) => {
        actions.loadTickets()
    }),
])
