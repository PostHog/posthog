import { MakeLogicType, actions, kea, path, reducers, selectors } from 'kea'

import { ConversationTicket, TicketChannel, TicketSlaState, TicketStatus, sampleTickets } from '../../data/tickets'

type ConversationsTicketsSceneLogicValues = {
    statusFilter: TicketStatus | 'all'
    channelFilter: TicketChannel | 'all'
    resolutionFilter: 'all' | 'ai' | 'human'
    slaFilter: TicketSlaState | 'all'
    tickets: ConversationTicket[]
    filteredTickets: ConversationTicket[]
    metrics: {
        open: number
        pending: number
        atRisk: number
        aiContainment: number
    }
}

type ConversationsTicketsSceneLogicActions = {
    setStatusFilter: (status: TicketStatus | 'all') => { status: TicketStatus | 'all' }
    setChannelFilter: (channel: TicketChannel | 'all') => { channel: TicketChannel | 'all' }
    setResolutionFilter: (resolution: 'all' | 'ai' | 'human') => { resolution: 'all' | 'ai' | 'human' }
    setSlaFilter: (sla: TicketSlaState | 'all') => { sla: TicketSlaState | 'all' }
}

export const conversationsTicketsSceneLogic = kea<
    MakeLogicType<ConversationsTicketsSceneLogicValues, ConversationsTicketsSceneLogicActions>
>([
    path(['products', 'conversations', 'frontend', 'scenes', 'tickets', 'conversationsTicketsSceneLogic']),
    actions({
        setStatusFilter: (status: TicketStatus | 'all') => ({ status }),
        setChannelFilter: (channel: TicketChannel | 'all') => ({ channel }),
        setResolutionFilter: (resolution: 'all' | 'ai' | 'human') => ({ resolution }),
        setSlaFilter: (sla: TicketSlaState | 'all') => ({ sla }),
    }),
    reducers({
        statusFilter: [
            'open' as TicketStatus | 'all',
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
        resolutionFilter: [
            'all' as 'all' | 'ai' | 'human',
            {
                setResolutionFilter: (_, { resolution }) => resolution,
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
        tickets: [() => [], (): ConversationTicket[] => sampleTickets],
        filteredTickets: [
            (s) => [s.tickets, s.statusFilter, s.channelFilter, s.resolutionFilter, s.slaFilter],
            (
                tickets: ConversationTicket[],
                statusFilter: TicketStatus | 'all',
                channelFilter: TicketChannel | 'all',
                resolutionFilter: 'all' | 'ai' | 'human',
                slaFilter: TicketSlaState | 'all'
            ) => {
                return tickets.filter((ticket: ConversationTicket) => {
                    if (statusFilter !== 'all' && ticket.status !== statusFilter) {
                        return false
                    }
                    if (channelFilter !== 'all' && ticket.channel !== channelFilter) {
                        return false
                    }
                    if (slaFilter !== 'all' && ticket.slaState !== slaFilter) {
                        return false
                    }
                    if (resolutionFilter === 'ai' && !ticket.aiContained) {
                        return false
                    }
                    if (resolutionFilter === 'human' && ticket.aiContained) {
                        return false
                    }
                    return true
                })
            },
        ],
        metrics: [
            (s) => [s.tickets],
            (tickets: ConversationTicket[]) => {
                const open = tickets.filter((t: ConversationTicket) => t.status === 'open').length
                const pending = tickets.filter((t: ConversationTicket) => t.status === 'pending').length
                const atRisk = tickets.filter((t: ConversationTicket) => t.slaState !== 'on-track').length
                const aiContainment = Math.round(
                    (tickets.filter((t: ConversationTicket) => t.aiContained).length / Math.max(tickets.length, 1)) *
                        100
                )
                return {
                    open,
                    pending,
                    atRisk,
                    aiContainment,
                }
            },
        ],
    }),
])
