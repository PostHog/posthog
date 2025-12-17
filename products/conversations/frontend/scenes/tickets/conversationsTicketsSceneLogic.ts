import { actions, afterMount, beforeUnmount, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'

import type { Ticket, TicketChannel, TicketPriority, TicketSlaState, TicketStatus } from '../../types'
import type { conversationsTicketsSceneLogicType } from './conversationsTicketsSceneLogicType'

const TICKETS_POLL_INTERVAL = 5000 // 5 seconds

export const conversationsTicketsSceneLogic = kea<conversationsTicketsSceneLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'tickets', 'conversationsTicketsSceneLogic']),
    actions({
        setStatusFilter: (status: TicketStatus | 'all') => ({ status }),
        setChannelFilter: (channel: TicketChannel | 'all') => ({ channel }),
        setSlaFilter: (sla: TicketSlaState | 'all') => ({ sla }),
        setPriorityFilter: (priority: TicketPriority | 'all') => ({ priority }),
        setAssigneeFilter: (assignee: 'all' | 'unassigned' | number) => ({ assignee }),
        setDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        loadTickets: true,
        setAutoUpdate: (enabled: boolean) => ({ enabled }),
        setPollingInterval: (interval: number) => ({ interval }),
        setTickets: (tickets: Ticket[]) => ({ tickets }),
    }),
    reducers({
        tickets: [
            [] as Ticket[],
            {
                setTickets: (_, { tickets }) => tickets,
            },
        ],
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
        priorityFilter: [
            'all' as TicketPriority | 'all',
            {
                setPriorityFilter: (_, { priority }) => priority,
            },
        ],
        assigneeFilter: [
            'all' as 'all' | 'unassigned' | number,
            {
                setAssigneeFilter: (_, { assignee }) => assignee,
            },
        ],
        dateFrom: [
            '-7d' as string | null,
            {
                setDateRange: (_, { dateFrom }) => dateFrom,
            },
        ],
        dateTo: [
            null as string | null,
            {
                setDateRange: (_, { dateTo }) => dateTo,
            },
        ],
        autoUpdateEnabled: [
            false as boolean,
            {
                setAutoUpdate: (_, { enabled }) => enabled,
            },
        ],
        pollingInterval: [
            null as NodeJS.Timeout | null,
            {
                setPollingInterval: (_, { interval }) => interval,
            },
        ],
    }),
    selectors({
        filteredTickets: [(s) => [s.tickets], (tickets: Ticket[]) => tickets],
    }),
    listeners(({ actions, values }) => ({
        loadTickets: async (_, breakpoint) => {
            await breakpoint(300)
            const params: Record<string, any> = {}
            if (values.statusFilter !== 'all') {
                params.status = values.statusFilter
            }
            if (values.priorityFilter !== 'all') {
                params.priority = values.priorityFilter
            }
            if (values.channelFilter !== 'all') {
                params.channel_source = values.channelFilter
            }
            if (values.assigneeFilter !== 'all') {
                params.assigned_to = values.assigneeFilter === 'unassigned' ? 'unassigned' : values.assigneeFilter
            }
            if (values.dateFrom) {
                params.date_from = values.dateFrom
            }
            if (values.dateTo) {
                params.date_to = values.dateTo
            }

            const response = await api.conversationsTickets.list(params)
            actions.setTickets(response.results || [])
        },
        setStatusFilter: () => {
            actions.loadTickets()
        },
        setPriorityFilter: () => {
            actions.loadTickets()
        },
        setChannelFilter: () => {
            actions.loadTickets()
        },
        setAssigneeFilter: () => {
            actions.loadTickets()
        },
        setDateRange: () => {
            actions.loadTickets()
        },
        setAutoUpdate: ({ enabled }) => {
            // Clear any existing interval
            if (values.pollingInterval) {
                clearInterval(values.pollingInterval)
                values.pollingInterval = null
            }

            // Start polling if enabled
            if (enabled) {
                values.pollingInterval = setInterval(() => {
                    actions.loadTickets()
                }, TICKETS_POLL_INTERVAL)
            }
        },
    })),
    afterMount(({ actions, values }) => {
        actions.loadTickets()
        // Clear any existing interval

        // Start new polling interval only if auto-update is enabled
        if (values.autoUpdateEnabled) {
            values.pollingInterval = setInterval(() => {
                actions.loadTickets()
            }, TICKETS_POLL_INTERVAL)
        }
    }),
    beforeUnmount(({ values }) => {
        // Clear polling interval on unmount
        if (values.pollingInterval) {
            clearInterval(values.pollingInterval)
            values.pollingInterval = null
        }
    }),
])
