import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { Sorting } from 'lib/lemon-ui/LemonTable/sorting'

import type {
    AssigneeFilterValue,
    Ticket,
    TicketChannel,
    TicketPriority,
    TicketSlaState,
    TicketStatus,
} from '../../types'
import type { supportTicketsSceneLogicType } from './supportTicketsSceneLogicType'

export const supportTicketsSceneLogic = kea<supportTicketsSceneLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'tickets', 'supportTicketsSceneLogic']),
    actions({
        setStatusFilter: (statuses: TicketStatus[]) => ({ statuses }),
        setChannelFilter: (channel: TicketChannel | 'all') => ({ channel }),
        setSlaFilter: (sla: TicketSlaState | 'all') => ({ sla }),
        setPriorityFilter: (priorities: TicketPriority[]) => ({ priorities }),
        setAssigneeFilter: (assignee: AssigneeFilterValue) => ({ assignee }),
        setDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setSorting: (sorting: Sorting | null) => ({ sorting }),
        loadTickets: true,
        setTickets: (tickets: Ticket[]) => ({ tickets }),
        setTicketsLoading: (loading: boolean) => ({ loading }),
    }),
    reducers({
        tickets: [
            [] as Ticket[],
            {
                setTickets: (_, { tickets }) => tickets,
            },
        ],
        ticketsLoading: [
            false,
            {
                loadTickets: () => true,
                setTickets: () => false,
                setTicketsLoading: (_, { loading }) => loading,
            },
        ],
        statusFilter: [
            [] as TicketStatus[],
            { persist: true },
            {
                setStatusFilter: (_, { statuses }) => statuses,
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
            [] as TicketPriority[],
            { persist: true },
            {
                setPriorityFilter: (_, { priorities }) => priorities,
            },
        ],
        assigneeFilter: [
            'all' as AssigneeFilterValue,
            { persist: true },
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
        sorting: [
            { columnKey: 'updated_at', order: -1 } as Sorting | null,
            {
                setSorting: (_, { sorting }) => sorting,
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
            if (values.statusFilter.length > 0) {
                params.status = values.statusFilter.join(',')
            }
            if (values.priorityFilter.length > 0) {
                params.priority = values.priorityFilter.join(',')
            }
            if (values.channelFilter !== 'all') {
                params.channel_source = values.channelFilter
            }
            if (values.assigneeFilter !== 'all') {
                if (values.assigneeFilter === 'unassigned') {
                    params.assignee = 'unassigned'
                } else if (values.assigneeFilter && typeof values.assigneeFilter === 'object') {
                    params.assignee = `${values.assigneeFilter.type}:${values.assigneeFilter.id}`
                }
            }
            if (values.dateFrom) {
                params.date_from = values.dateFrom
            }
            if (values.dateTo) {
                params.date_to = values.dateTo
            }
            if (values.sorting) {
                params.ordering = `${values.sorting.order === -1 ? '-' : ''}${values.sorting.columnKey}`
            }

            try {
                const response = await api.conversationsTickets.list(params)
                actions.setTickets(response.results || [])
            } catch {
                lemonToast.error('Failed to load tickets')
                actions.setTicketsLoading(false)
            }
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
        setSorting: () => {
            actions.loadTickets()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadTickets()
    }),
])
