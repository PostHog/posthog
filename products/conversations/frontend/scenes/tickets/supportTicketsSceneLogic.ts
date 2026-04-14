import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { Sorting } from 'lib/lemon-ui/LemonTable/sorting'
import { teamLogic } from 'scenes/teamLogic'

import type {
    AssigneeFilterValue,
    SavedTicketView,
    Ticket,
    TicketChannel,
    TicketPriority,
    TicketSlaState,
    TicketStatus,
    TicketViewFilters,
} from '../../types'
import type { supportTicketsSceneLogicType } from './supportTicketsSceneLogicType'

export const SUPPORT_TICKETS_PAGE_SIZE = 20

export interface SupportTicketsSceneLogicProps {
    key?: string
    distinctIds?: string[]
}

export const supportTicketsSceneLogic = kea<supportTicketsSceneLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'tickets', 'supportTicketsSceneLogic']),
    props({} as SupportTicketsSceneLogicProps),
    key((props: SupportTicketsSceneLogicProps) => props?.key || 'SupportTicketsScene'),
    actions({
        setStatusFilter: (statuses: TicketStatus[]) => ({ statuses }),
        setChannelFilter: (channel: TicketChannel | 'all') => ({ channel }),
        setSlaFilter: (sla: TicketSlaState | 'all') => ({ sla }),
        setPriorityFilter: (priorities: TicketPriority[]) => ({ priorities }),
        setAssigneeFilter: (assignee: AssigneeFilterValue) => ({ assignee }),
        setTagsFilter: (tags: string[]) => ({ tags }),
        setDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setSorting: (sorting: Sorting | null) => ({ sorting }),
        setCurrentPage: (page: number) => ({ page }),
        loadTickets: true,
        setTickets: (tickets: Ticket[]) => ({ tickets }),
        setTotalCount: (count: number) => ({ count }),
        setTicketsLoading: (loading: boolean) => ({ loading }),
        applyViewFilters: (filters: TicketViewFilters) => ({ filters }),
        setActiveView: (view: SavedTicketView | null) => ({ view }),
        clearActiveView: true,
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
        currentPage: [
            1,
            {
                setCurrentPage: (_, { page }) => page,
            },
        ],
        totalCount: [
            0,
            {
                setTotalCount: (_, { count }) => count,
            },
        ],
        statusFilter: [
            [] as TicketStatus[],
            { persist: true },
            {
                setStatusFilter: (_, { statuses }) => statuses,
                applyViewFilters: (state, { filters }) => filters.status ?? state,
            },
        ],
        channelFilter: [
            'all' as TicketChannel | 'all',
            {
                setChannelFilter: (_, { channel }) => channel,
                applyViewFilters: (state, { filters }) => filters.channel ?? state,
            },
        ],
        slaFilter: [
            'all' as TicketSlaState | 'all',
            {
                setSlaFilter: (_, { sla }) => sla,
                applyViewFilters: (state, { filters }) => filters.sla ?? state,
            },
        ],
        priorityFilter: [
            [] as TicketPriority[],
            { persist: true },
            {
                setPriorityFilter: (_, { priorities }) => priorities,
                applyViewFilters: (state, { filters }) => filters.priority ?? state,
            },
        ],
        assigneeFilter: [
            'all' as AssigneeFilterValue,
            { persist: true },
            {
                setAssigneeFilter: (_, { assignee }) => assignee,
                applyViewFilters: (state, { filters }) => filters.assignee ?? state,
            },
        ],
        tagsFilter: [
            [] as string[],
            { persist: true },
            {
                setTagsFilter: (_, { tags }) => tags,
                applyViewFilters: (state, { filters }) => filters.tags ?? state,
            },
        ],
        dateFrom: [
            '-7d' as string | null,
            { persist: true },
            {
                setDateRange: (_, { dateFrom }) => dateFrom,
                applyViewFilters: (state, { filters }) => (filters.dateFrom !== undefined ? filters.dateFrom : state),
            },
        ],
        dateTo: [
            null as string | null,
            { persist: true },
            {
                setDateRange: (_, { dateTo }) => dateTo,
                applyViewFilters: (state, { filters }) => (filters.dateTo !== undefined ? filters.dateTo : state),
            },
        ],
        sorting: [
            { columnKey: 'updated_at', order: -1 } as Sorting | null,
            {
                setSorting: (_, { sorting }) => sorting,
                applyViewFilters: (state, { filters }) => (filters.sorting !== undefined ? filters.sorting : state),
            },
        ],
        activeView: [
            null as SavedTicketView | null,
            {
                setActiveView: (_, { view }) => view,
                clearActiveView: () => null,
            },
        ],
    }),
    selectors({
        orderBy: [
            (s) => [s.sorting],
            (sorting: Sorting | null): string => {
                if (!sorting) {
                    return '-updated_at'
                }
                const prefix = sorting.order === 1 ? '' : '-'
                return `${prefix}${sorting.columnKey}`
            },
        ],
        currentFilters: [
            (s) => [
                s.statusFilter,
                s.priorityFilter,
                s.channelFilter,
                s.slaFilter,
                s.assigneeFilter,
                s.tagsFilter,
                s.dateFrom,
                s.dateTo,
                s.sorting,
            ],
            (
                status: TicketStatus[],
                priority: TicketPriority[],
                channel: TicketChannel | 'all',
                sla: TicketSlaState | 'all',
                assignee: AssigneeFilterValue,
                tags: string[],
                dateFrom: string | null,
                dateTo: string | null,
                sorting: Sorting | null
            ): TicketViewFilters => ({
                status,
                priority,
                channel,
                sla,
                assignee,
                tags,
                dateFrom,
                dateTo,
                sorting,
            }),
        ],
    }),
    listeners(({ actions, values, props }) => ({
        loadTickets: async (_, breakpoint) => {
            await breakpoint(300)
            const params: Record<string, any> = {}

            if (props.distinctIds && props.distinctIds.length > 0) {
                params.distinct_ids = props.distinctIds.join(',')
            }

            if (values.statusFilter.length > 0) {
                params.status = values.statusFilter.join(',')
            }
            if (values.priorityFilter.length > 0) {
                params.priority = values.priorityFilter.join(',')
            }
            if (values.channelFilter !== 'all') {
                params.channel_source = values.channelFilter
            }
            if (values.slaFilter !== 'all') {
                params.sla = values.slaFilter
            }
            if (values.assigneeFilter !== 'all') {
                if (values.assigneeFilter === 'unassigned') {
                    params.assignee = 'unassigned'
                } else if (values.assigneeFilter && typeof values.assigneeFilter === 'object') {
                    params.assignee = `${values.assigneeFilter.type}:${values.assigneeFilter.id}`
                }
            }
            if (values.tagsFilter.length > 0) {
                params.tags = JSON.stringify(values.tagsFilter)
            }
            if (values.dateFrom) {
                params.date_from = values.dateFrom
            }
            if (values.dateTo) {
                params.date_to = values.dateTo
            }
            params.order_by = values.orderBy
            params.limit = SUPPORT_TICKETS_PAGE_SIZE
            params.offset = (values.currentPage - 1) * SUPPORT_TICKETS_PAGE_SIZE

            try {
                const response = await api.conversationsTickets.list(params)
                actions.setTickets(response.results || [])
                actions.setTotalCount(response.count ?? response.results?.length ?? 0)
            } catch {
                lemonToast.error('Failed to load tickets')
                actions.setTicketsLoading(false)
            }
        },
        applyViewFilters: () => {
            actions.setCurrentPage(1)
        },
        setCurrentPage: () => {
            actions.loadTickets()
        },
        setStatusFilter: () => {
            actions.clearActiveView()
            actions.setCurrentPage(1)
        },
        setPriorityFilter: () => {
            actions.clearActiveView()
            actions.setCurrentPage(1)
        },
        setChannelFilter: () => {
            actions.clearActiveView()
            actions.setCurrentPage(1)
        },
        setSlaFilter: () => {
            actions.clearActiveView()
            actions.setCurrentPage(1)
        },
        setAssigneeFilter: () => {
            actions.clearActiveView()
            actions.setCurrentPage(1)
        },
        setTagsFilter: () => {
            actions.clearActiveView()
            actions.setCurrentPage(1)
        },
        setDateRange: () => {
            actions.clearActiveView()
            actions.setCurrentPage(1)
        },
        setSorting: () => {
            actions.clearActiveView()
            actions.setCurrentPage(1)
        },
        setActiveView: ({ view }) => {
            if (view) {
                const { searchParams } = router.values
                router.actions.replace(router.values.location.pathname, { ...searchParams, view: view.short_id })
            }
        },
        clearActiveView: () => {
            const { searchParams } = router.values
            if (searchParams.view) {
                const { view: _, ...rest } = searchParams
                router.actions.replace(router.values.location.pathname, rest)
            }
        },
    })),
    afterMount(({ actions }) => {
        const { searchParams } = router.values
        const viewShortId = searchParams.view
        if (viewShortId) {
            const teamId = teamLogic.values.currentTeamId
            api.get(`api/environments/${teamId}/conversations/views/${viewShortId}`)
                .then((view: SavedTicketView) => {
                    actions.applyViewFilters(view.filters || {})
                    actions.setActiveView(view)
                })
                .catch(() => {
                    lemonToast.error('Failed to load saved view')
                    actions.loadTickets()
                })
            return
        }
        actions.loadTickets()
    }),
])
