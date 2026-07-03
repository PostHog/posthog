import { actions, kea, path, reducers } from 'kea'

import type { ticketSidebarLogicType } from './ticketSidebarLogicType'

export const TICKET_SIDEBAR_WIDGETS = [
    { key: 'customer', label: 'Customer', description: 'Who opened the ticket, with a link to their person profile' },
    { key: 'related-groups', label: 'Related groups', description: 'Groups the customer belongs to' },
    { key: 'staff-actions', label: 'Staff actions', description: 'Internal staff tools for this ticket' },
    { key: 'ai-triage', label: 'AI triage', description: 'AI triage outcome and knowledge gaps' },
    {
        key: 'session-recording',
        label: 'Session recording',
        description: 'Replay of the session the ticket came from',
    },
    { key: 'recent-events', label: 'Recent events', description: 'Events around the time the ticket was created' },
    { key: 'exceptions', label: 'Exceptions', description: "Exceptions from the customer's session" },
    { key: 'previous-tickets', label: 'Previous tickets', description: "The customer's earlier tickets" },
    { key: 'activity', label: 'Ticket activity history', description: 'Audit log of changes to this ticket' },
] as const

export type TicketSidebarWidgetKey = (typeof TICKET_SIDEBAR_WIDGETS)[number]['key']

export const ticketSidebarLogic = kea<ticketSidebarLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'ticket', 'ticketSidebarLogic']),
    actions({
        setWidgetVisible: (widget: TicketSidebarWidgetKey, visible: boolean) => ({ widget, visible }),
        setWidgetsModalOpen: (open: boolean) => ({ open }),
    }),
    reducers({
        widgetsModalOpen: [
            false,
            {
                setWidgetsModalOpen: (_, { open }) => open,
            },
        ],
        hiddenWidgets: [
            [] as TicketSidebarWidgetKey[],
            { persist: true },
            {
                setWidgetVisible: (state, { widget, visible }) => {
                    if (visible) {
                        return state.filter((w) => w !== widget)
                    }
                    return state.includes(widget) ? state : [...state, widget]
                },
            },
        ],
    }),
])
