import { MakeLogicType, actions, kea, path, reducers } from 'kea'

import { TicketSlaState, TicketStatus, ticketDetail } from '../../data/tickets'

type TicketPriority = 'low' | 'medium' | 'high'

type ConversationsTicketSceneLogicValues = {
    status: TicketStatus
    priority: TicketPriority
    aiContainment: boolean
    assignedTo: string
    slaRisk: TicketSlaState
}

type ConversationsTicketSceneLogicActions = {
    setStatus: (status: TicketStatus) => { status: TicketStatus }
    setPriority: (priority: TicketPriority) => { priority: TicketPriority }
    setAiContainment: (aiContainment: boolean) => { aiContainment: boolean }
    setAssignedTo: (assignedTo: string) => { assignedTo: string }
    setSlaRisk: (slaRisk: TicketSlaState) => { slaRisk: TicketSlaState }
}

export const conversationsTicketSceneLogic = kea<
    MakeLogicType<ConversationsTicketSceneLogicValues, ConversationsTicketSceneLogicActions>
>([
    path(['products', 'conversations', 'frontend', 'scenes', 'ticket', 'conversationsTicketSceneLogic']),
    actions({
        setStatus: (status: TicketStatus) => ({ status }),
        setPriority: (priority: TicketPriority) => ({ priority }),
        setAiContainment: (aiContainment: boolean) => ({ aiContainment }),
        setAssignedTo: (assignedTo: string) => ({ assignedTo }),
        setSlaRisk: (slaRisk: TicketSlaState) => ({ slaRisk }),
    }),
    reducers({
        status: [
            ticketDetail.status as TicketStatus,
            {
                setStatus: (_, { status }) => status,
            },
        ],
        priority: [
            ticketDetail.priority as TicketPriority,
            {
                setPriority: (_, { priority }) => priority,
            },
        ],
        aiContainment: [
            ticketDetail.aiContainment,
            {
                setAiContainment: (_, { aiContainment }) => aiContainment,
            },
        ],
        assignedTo: [
            ticketDetail.assignedTo,
            {
                setAssignedTo: (_, { assignedTo }) => assignedTo,
            },
        ],
        slaRisk: [
            ticketDetail.sla.risk,
            {
                setSlaRisk: (_, { slaRisk }) => slaRisk,
            },
        ],
    }),
])
