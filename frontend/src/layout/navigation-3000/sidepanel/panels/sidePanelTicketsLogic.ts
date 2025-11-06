import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
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
    }),
    loaders(({ values }) => ({
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
            },
        ],
    })),
    selectors({
        tickets: [(s) => [s.ticketsResponse], (ticketsResponse) => ticketsResponse.tickets],
        ticketsCount: [(s) => [s.ticketsResponse], (ticketsResponse) => ticketsResponse.count],
        hasError: [(s) => [s.ticketsResponse], (ticketsResponse) => !!ticketsResponse.error],
        hasPendingTickets: [
            (s) => [s.tickets],
            (tickets) => tickets.some((ticket) => ticket.status === 'pending'),
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadTickets()
    }),
])

