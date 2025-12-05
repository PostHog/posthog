import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { Ticket, TicketChannel, TicketSlaState, TicketStatus } from '../../types'
import type { conversationsTicketsSceneLogicType } from './conversationsTicketsSceneLogicType'

export const conversationsTicketsSceneLogic = kea<conversationsTicketsSceneLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'tickets', 'conversationsTicketsSceneLogic']),
    actions({
        setStatusFilter: (status: TicketStatus | 'all') => ({ status }),
        setChannelFilter: (channel: TicketChannel | 'all') => ({ channel }),
        setSlaFilter: (sla: TicketSlaState | 'all') => ({ sla }),
        loadTickets: true,
    }),
    loaders(({ values }) => ({
        tickets: [
            [] as Ticket[],
            {
                loadTickets: async () => {
                    const params: Record<string, any> = {}
                    if (values.statusFilter !== 'all') {
                        params.status = values.statusFilter
                    }
                    const response = await api.conversationsTickets.list(params)
                    return response.results
                },
            },
        ],
    })),
    reducers({
        statusFilter: [
            'all' as TicketStatus | 'all',
            {
                setStatusFilter: (_, { status }) => status,
            },
        ],
        channelFilter: [
            'all' as TicketChannel | 'all',
            {
                setChannelFilter: (_, { channel }) => channel,
            },
        ],
        slaFilter: [
            'all' as TicketSlaState | 'all',
            {
                setSlaFilter: (_, { sla }) => sla,
            },
        ],
    }),
    selectors({
        filteredTickets: [
            (s) => [s.tickets, s.channelFilter],
            (tickets: Ticket[], channelFilter: TicketChannel | 'all') => {
                return tickets.filter((ticket: Ticket) => {
                    if (channelFilter !== 'all' && ticket.channel_source !== channelFilter) {
                        return false
                    }
                    // SLA filtering would need to be calculated based on created_at/updated_at
                    // For now, skip SLA filter since we don't have that data from backend yet
                    return true
                })
            },
        ],
    }),
    listeners(({ actions }) => ({
        setStatusFilter: () => {
            actions.loadTickets()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadTickets()
    }),
])
