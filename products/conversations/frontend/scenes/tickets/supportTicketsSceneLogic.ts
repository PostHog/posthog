import { MakeLogicType, actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { Sorting } from 'lib/lemon-ui/LemonTable/sorting'
import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'
import { objectsEqual } from 'lib/utils/objects'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlLevel, AccessControlResourceType, TeamType } from '~/types'

import { conversationsViewsRetrieve } from '../../generated/api'
import { normalizeAssigneeFilter } from '../../types'
import type {
    AITriageFilterValue,
    AssigneeFilterEntry,
    SavedTicketView,
    Ticket,
    TicketChannel,
    TicketPriority,
    TicketSlaState,
    TicketStatus,
    TicketTagsMatch,
    TicketViewFilters,
} from '../../types'

export const SUPPORT_TICKETS_PAGE_SIZE = 20

// Must mirror the filter reducers' defaults below. The date range is deliberately
// omitted: it's a persisted user preference, so clearing a view restores the
// pre-view selection (dateRangeBeforeView), falling back to all time.
const DEFAULT_TICKET_FILTERS: TicketViewFilters = {
    status: [],
    priority: [],
    channel: 'all',
    sla: 'all',
    aiTriageResult: [],
    assignee: 'all',
    tags: [],
    tagsMatch: 'any',
    tagsExclude: [],
    sorting: { columnKey: 'updated_at', order: -1 },
    search: '',
}

const DEFAULT_SORTING: Sorting = { columnKey: 'updated_at', order: -1 }
const DEFAULT_ORDER_BY = '-updated_at'

// Shareable ticket-filter query params. Date range stays a personal preference,
// while free-text search stays out of URLs because it can contain customer data.
const FILTER_URL_PARAM_KEYS = [
    'status',
    'priority',
    'ai_triage_result',
    'channel',
    'sla',
    'assignee',
    'tags',
    'tags_match',
    'tags_exclude',
    'order_by',
] as const

function sortingToOrderBy(sorting: Sorting | null | undefined): string {
    if (!sorting) {
        return DEFAULT_ORDER_BY
    }
    return `${sorting.order === 1 ? '' : '-'}${sorting.columnKey}`
}

function orderByToSorting(orderBy: string): Sorting {
    return { columnKey: orderBy.replace(/^-/, ''), order: orderBy.startsWith('-') ? -1 : 1 }
}

function encodeAssigneeEntry(entry: AssigneeFilterEntry): string {
    return entry === 'unassigned' ? 'unassigned' : `${entry.type}:${entry.id}`
}

// kea-router hands back arrays for multi-value params, but a hand-typed single
// value can arrive as a bare string — coerce both to a string array.
function toStringArray(value: unknown): string[] {
    if (Array.isArray(value)) {
        return value.map(String)
    }
    if (typeof value === 'string' && value !== '') {
        return [value]
    }
    return []
}

function decodeAssignee(value: unknown): AssigneeFilterEntry[] {
    const entries = toStringArray(value).map((token): AssigneeFilterEntry | null => {
        if (token === 'unassigned') {
            return 'unassigned'
        }
        const separator = token.indexOf(':')
        const type = token.slice(0, separator)
        const id = token.slice(separator + 1)
        return (type === 'user' || type === 'role') && id ? { type, id } : null
    })
    return normalizeAssigneeFilter(entries.filter((entry): entry is AssigneeFilterEntry => entry !== null))
}

// Canonical URL representation of the filters. Only non-default values are
// emitted so shared links stay readable.
function filtersToUrlParams(filters: TicketViewFilters): Record<string, any> {
    const params: Record<string, any> = {}
    if (filters.status?.length) {
        params.status = filters.status
    }
    if (filters.priority?.length) {
        params.priority = filters.priority
    }
    if (filters.aiTriageResult?.length) {
        params.ai_triage_result = filters.aiTriageResult
    }
    if (filters.channel && filters.channel !== 'all') {
        params.channel = filters.channel
    }
    if (filters.sla && filters.sla !== 'all') {
        params.sla = filters.sla
    }
    const assignee = normalizeAssigneeFilter(filters.assignee)
    if (assignee.length) {
        params.assignee = assignee.map(encodeAssigneeEntry)
    }
    if (filters.tags?.length) {
        params.tags = filters.tags
        if (filters.tagsMatch === 'all') {
            params.tags_match = 'all'
        }
    }
    if (filters.tagsExclude?.length) {
        params.tags_exclude = filters.tagsExclude
    }
    const orderBy = sortingToOrderBy(filters.sorting)
    if (orderBy !== DEFAULT_ORDER_BY) {
        params.order_by = orderBy
    }
    return params
}

// A shared link fully determines the filter set, so params absent from the URL
// reset to their defaults rather than keeping persisted state. Date range is
// omitted so the recipient's own window is preserved.
function urlParamsToFilters(searchParams: Record<string, any>): TicketViewFilters {
    return {
        status: toStringArray(searchParams.status) as TicketStatus[],
        priority: toStringArray(searchParams.priority) as TicketPriority[],
        aiTriageResult: toStringArray(searchParams.ai_triage_result) as AITriageFilterValue[],
        channel: (searchParams.channel as TicketChannel) ?? 'all',
        sla: (searchParams.sla as TicketSlaState) ?? 'all',
        assignee: decodeAssignee(searchParams.assignee),
        tags: toStringArray(searchParams.tags),
        tagsMatch: searchParams.tags_match === 'all' ? 'all' : 'any',
        tagsExclude: toStringArray(searchParams.tags_exclude),
        search: '',
        sorting: searchParams.order_by ? orderByToSorting(String(searchParams.order_by)) : { ...DEFAULT_SORTING },
    }
}

function hasFilterParams(searchParams: Record<string, any>): boolean {
    return FILTER_URL_PARAM_KEYS.some((paramKey) => searchParams[paramKey] !== undefined)
}

// Compare a URL against the current filters via their canonical encodings, so
// non-canonical inputs (single-value strings, redundant defaults) don't read as
// a difference and trigger a needless re-apply loop.
function urlFiltersMatchState(searchParams: Record<string, any>, currentFilters: TicketViewFilters): boolean {
    return (
        !currentFilters.search &&
        objectsEqual(filtersToUrlParams(urlParamsToFilters(searchParams)), filtersToUrlParams(currentFilters))
    )
}

export interface SupportTicketsSceneLogicProps {
    key?: string
    distinctIds?: string[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface supportTicketsSceneLogicValues {
    activeView: SavedTicketView | null
    aiEnabled: boolean
    aiTriageResultFilter: AITriageFilterValue[]
    assigneeFilter: AssigneeFilterEntry[]
    assigneeFilterEntries: AssigneeFilterEntry[]
    bulkUpdating: boolean
    channelFilter: TicketChannel | 'all'
    currentFilters: TicketViewFilters
    currentPage: number
    dateFrom: string | null
    dateRangeBeforeView: {
        dateFrom: string | null
        dateTo: string | null
    } | null
    dateTo: string | null
    editableSelectedTicketIds: string[]
    hasActiveFilters: boolean
    orderBy: string
    priorityFilter: TicketPriority[]
    searchQuery: string
    selectedTicketIds: string[]
    selectedTickets: Ticket[]
    slaFilter: TicketSlaState | 'all'
    sorting: Sorting | null
    statusFilter: TicketStatus[]
    tagsExcludeFilter: string[]
    tagsFilter: string[]
    tagsMatch: TicketTagsMatch
    tickets: Ticket[]
    ticketsLoading: boolean
    totalCount: number
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface supportTicketsSceneLogicActions {
    applyUrlFilters: (filters: TicketViewFilters) => {
        filters: TicketViewFilters
    }
    applyView: (view: SavedTicketView) => {
        view: SavedTicketView
    }
    applyViewFilters: (filters: TicketViewFilters) => {
        filters: TicketViewFilters
    }
    bulkUpdateStatus: (
        ids: string[],
        status: TicketStatus
    ) => {
        ids: string[]
        status: TicketStatus
    }
    clearActiveView: () => {
        value: true
    }
    clearFiltersKeepingSearch: () => {
        value: true
    }
    clearSelectedTickets: () => {
        value: true
    }
    loadSavedView: (shortId: string) => {
        shortId: string
    }
    loadTickets: () => {
        value: true
    }
    resetFilters: () => {
        value: true
    }
    setActiveView: (view: SavedTicketView | null) => {
        view: SavedTicketView | null
    }
    setAiTriageResultFilter: (results: AITriageFilterValue[]) => {
        results: AITriageFilterValue[]
    }
    setAssigneeFilter: (assignees: AssigneeFilterEntry[]) => {
        assignees: AssigneeFilterEntry[]
    }
    setBulkUpdating: (updating: boolean) => {
        updating: boolean
    }
    setChannelFilter: (channel: TicketChannel | 'all') => {
        channel: TicketChannel | 'all'
    }
    setCurrentPage: (page: number) => {
        page: number
    }
    setDateRange: (
        dateFrom: string | null,
        dateTo: string | null
    ) => {
        dateFrom: string | null
        dateTo: string | null
    }
    setDateRangeBeforeView: (
        dateFrom: string | null,
        dateTo: string | null
    ) => {
        dateFrom: string | null
        dateTo: string | null
    }
    setPriorityFilter: (priorities: TicketPriority[]) => {
        priorities: TicketPriority[]
    }
    setSearchQuery: (query: string) => {
        query: string
    }
    setSelectedTicketIds: (ids: string[]) => {
        ids: string[]
    }
    setSlaFilter: (sla: TicketSlaState | 'all') => {
        sla: TicketSlaState | 'all'
    }
    setSorting: (sorting: Sorting | null) => {
        sorting: Sorting | null
    }
    setStatusFilter: (statuses: TicketStatus[]) => {
        statuses: TicketStatus[]
    }
    setTagsExcludeFilter: (tags: string[]) => {
        tags: string[]
    }
    setTagsFilter: (tags: string[]) => {
        tags: string[]
    }
    setTagsMatch: (match: TicketTagsMatch) => {
        match: TicketTagsMatch
    }
    setTickets: (tickets: Ticket[]) => {
        tickets: Ticket[]
    }
    setTicketsLoading: (loading: boolean) => {
        loading: boolean
    }
    setTotalCount: (count: number) => {
        count: number
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface supportTicketsSceneLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        aiEnabled: (currentTeam: TeamType | null | import('~/types').TeamPublicType) => boolean
        orderBy: (sorting: Sorting | null) => string
        selectedTickets: (tickets: Ticket[], selectedTicketIds: string[]) => Ticket[]
        editableSelectedTicketIds: (selectedTickets: Ticket[]) => string[]
        assigneeFilterEntries: (assigneeFilter: AssigneeFilterEntry[]) => AssigneeFilterEntry[]
        hasActiveFilters: (
            statusFilter: TicketStatus[],
            priorityFilter: TicketPriority[],
            channelFilter: TicketChannel | 'all',
            slaFilter: TicketSlaState | 'all',
            aiTriageResultFilter: AITriageFilterValue[],
            assigneeFilterEntries: AssigneeFilterEntry[],
            tagsFilter: string[],
            tagsExcludeFilter: string[],
            dateFrom: string | null,
            dateTo: string | null
        ) => boolean
        currentFilters: (
            statusFilter: TicketStatus[],
            priorityFilter: TicketPriority[],
            channelFilter: TicketChannel | 'all',
            slaFilter: TicketSlaState | 'all',
            aiTriageResultFilter: AITriageFilterValue[],
            assigneeFilterEntries: AssigneeFilterEntry[],
            tagsFilter: string[],
            tagsMatch: TicketTagsMatch,
            tagsExcludeFilter: string[],
            dateFrom: string | null,
            dateTo: string | null,
            sorting: Sorting | null,
            searchQuery: string
        ) => TicketViewFilters
    }
}

export type supportTicketsSceneLogicType = MakeLogicType<
    supportTicketsSceneLogicValues,
    supportTicketsSceneLogicActions,
    SupportTicketsSceneLogicProps,
    supportTicketsSceneLogicMeta
>

export const supportTicketsSceneLogic = kea<supportTicketsSceneLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'tickets', 'supportTicketsSceneLogic']),
    props({} as SupportTicketsSceneLogicProps),
    key((props: SupportTicketsSceneLogicProps) => props?.key || 'SupportTicketsScene'),
    actions({
        setStatusFilter: (statuses: TicketStatus[]) => ({ statuses }),
        setChannelFilter: (channel: TicketChannel | 'all') => ({ channel }),
        setSlaFilter: (sla: TicketSlaState | 'all') => ({ sla }),
        setPriorityFilter: (priorities: TicketPriority[]) => ({ priorities }),
        setAiTriageResultFilter: (results: AITriageFilterValue[]) => ({ results }),
        setAssigneeFilter: (assignees: AssigneeFilterEntry[]) => ({ assignees }),
        setTagsFilter: (tags: string[]) => ({ tags }),
        setTagsMatch: (match: TicketTagsMatch) => ({ match }),
        setTagsExcludeFilter: (tags: string[]) => ({ tags }),
        setDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setSorting: (sorting: Sorting | null) => ({ sorting }),
        setSearchQuery: (query: string) => ({ query }),
        setCurrentPage: (page: number) => ({ page }),
        loadTickets: true,
        setTickets: (tickets: Ticket[]) => ({ tickets }),
        setTotalCount: (count: number) => ({ count }),
        setTicketsLoading: (loading: boolean) => ({ loading }),
        applyViewFilters: (filters: TicketViewFilters) => ({ filters }),
        applyUrlFilters: (filters: TicketViewFilters) => ({ filters }),
        applyView: (view: SavedTicketView) => ({ view }),
        loadSavedView: (shortId: string) => ({ shortId }),
        setActiveView: (view: SavedTicketView | null) => ({ view }),
        clearActiveView: true,
        resetFilters: true,
        clearFiltersKeepingSearch: true,
        setDateRangeBeforeView: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        bulkUpdateStatus: (ids: string[], status: TicketStatus) => ({ ids, status }),
        setBulkUpdating: (updating: boolean) => ({ updating }),
        setSelectedTicketIds: (ids: string[]) => ({ ids }),
        clearSelectedTickets: true,
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
            { persist: true },
            {
                setChannelFilter: (_, { channel }) => channel,
                applyViewFilters: (state, { filters }) => filters.channel ?? state,
            },
        ],
        slaFilter: [
            'all' as TicketSlaState | 'all',
            { persist: true },
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
        aiTriageResultFilter: [
            [] as AITriageFilterValue[],
            { persist: true },
            {
                setAiTriageResultFilter: (_, { results }) => results,
                applyViewFilters: (state, { filters }) => filters.aiTriageResult ?? state,
            },
        ],
        assigneeFilter: [
            [] as AssigneeFilterEntry[],
            { persist: true },
            {
                setAssigneeFilter: (_, { assignees }) => assignees,
                applyViewFilters: (state, { filters }) =>
                    filters.assignee != null ? normalizeAssigneeFilter(filters.assignee) : state,
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
        tagsMatch: [
            'any' as TicketTagsMatch,
            { persist: true },
            {
                setTagsMatch: (_, { match }) => match,
                applyViewFilters: (state, { filters }) => filters.tagsMatch ?? state,
            },
        ],
        tagsExcludeFilter: [
            [] as string[],
            { persist: true },
            {
                setTagsExcludeFilter: (_, { tags }) => tags,
                applyViewFilters: (state, { filters }) => filters.tagsExclude ?? state,
            },
        ],
        searchQuery: [
            '' as string,
            { persist: true },
            {
                setSearchQuery: (_, { query }) => query,
                applyViewFilters: (state, { filters }) => filters.search ?? state,
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
        dateRangeBeforeView: [
            null as { dateFrom: string | null; dateTo: string | null } | null,
            { persist: true },
            {
                setDateRangeBeforeView: (_, { dateFrom, dateTo }) => ({ dateFrom, dateTo }),
                // A manual date pick is the user's new preference, so the snapshot is obsolete
                setDateRange: () => null,
            },
        ],
        bulkUpdating: [
            false,
            {
                setBulkUpdating: (_, { updating }) => updating,
            },
        ],
        selectedTicketIds: [
            [] as string[],
            {
                setSelectedTicketIds: (_, { ids }) => ids,
                clearSelectedTickets: () => [],
                loadTickets: () => [],
            },
        ],
    }),
    selectors({
        aiEnabled: [
            () => [teamLogic.selectors.currentTeam],
            (currentTeam: TeamType | null): boolean => !!currentTeam?.conversations_settings?.ai_suggestions_enabled,
        ],
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
        selectedTickets: [
            (s) => [s.tickets, s.selectedTicketIds],
            (tickets: Ticket[], selectedIds: string[]): Ticket[] => {
                const idSet = new Set(selectedIds)
                return tickets.filter((t) => idSet.has(t.id))
            },
        ],
        editableSelectedTicketIds: [
            (s) => [s.selectedTickets],
            (selectedTickets: Ticket[]): string[] =>
                selectedTickets
                    .filter(
                        (ticket) =>
                            !ticket.user_access_level ||
                            accessLevelSatisfied(
                                AccessControlResourceType.Ticket,
                                ticket.user_access_level,
                                AccessControlLevel.Editor
                            )
                    )
                    .map((ticket) => ticket.id),
        ],
        assigneeFilterEntries: [
            (s) => [s.assigneeFilter],
            (assigneeFilter: AssigneeFilterEntry[]): AssigneeFilterEntry[] => normalizeAssigneeFilter(assigneeFilter),
        ],
        hasActiveFilters: [
            (s) => [
                s.statusFilter,
                s.priorityFilter,
                s.channelFilter,
                s.slaFilter,
                s.aiTriageResultFilter,
                s.assigneeFilterEntries,
                s.tagsFilter,
                s.tagsExcludeFilter,
                s.dateFrom,
                s.dateTo,
            ],
            (
                status: TicketStatus[],
                priority: TicketPriority[],
                channel: TicketChannel | 'all',
                sla: TicketSlaState | 'all',
                aiTriageResult: AITriageFilterValue[],
                assignee: AssigneeFilterEntry[],
                tags: string[],
                tagsExclude: string[],
                dateFrom: string | null,
                dateTo: string | null
            ): boolean =>
                status.length > 0 ||
                priority.length > 0 ||
                channel !== 'all' ||
                sla !== 'all' ||
                aiTriageResult.length > 0 ||
                assignee.length > 0 ||
                tags.length > 0 ||
                tagsExclude.length > 0 ||
                dateFrom !== null ||
                dateTo !== null,
        ],
        currentFilters: [
            (s) => [
                s.statusFilter,
                s.priorityFilter,
                s.channelFilter,
                s.slaFilter,
                s.aiTriageResultFilter,
                s.assigneeFilterEntries,
                s.tagsFilter,
                s.tagsMatch,
                s.tagsExcludeFilter,
                s.dateFrom,
                s.dateTo,
                s.sorting,
                s.searchQuery,
            ],
            (
                status: TicketStatus[],
                priority: TicketPriority[],
                channel: TicketChannel | 'all',
                sla: TicketSlaState | 'all',
                aiTriageResult: AITriageFilterValue[],
                assignee: AssigneeFilterEntry[],
                tags: string[],
                tagsMatch: TicketTagsMatch,
                tagsExclude: string[],
                dateFrom: string | null,
                dateTo: string | null,
                sorting: Sorting | null,
                search: string
            ): TicketViewFilters => ({
                status,
                priority,
                channel,
                sla,
                aiTriageResult,
                assignee,
                tags,
                tagsMatch,
                tagsExclude,
                dateFrom,
                dateTo,
                sorting,
                search: search || undefined,
            }),
        ],
    }),
    listeners(({ actions, values, props, cache }) => ({
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
            if (values.aiEnabled && values.aiTriageResultFilter.length > 0) {
                params.ai_triage_result = values.aiTriageResultFilter.join(',')
            }
            if (values.channelFilter !== 'all') {
                params.channel_source = values.channelFilter
            }
            if (values.slaFilter !== 'all') {
                params.sla = values.slaFilter
            }
            if (values.assigneeFilterEntries.length > 0) {
                params.assignee = values.assigneeFilterEntries
                    .map((entry) => (entry === 'unassigned' ? 'unassigned' : `${entry.type}:${entry.id}`))
                    .join(',')
            }
            if (values.tagsFilter.length > 0) {
                params[values.tagsMatch === 'all' ? 'tags_all' : 'tags'] = JSON.stringify(values.tagsFilter)
            }
            if (values.tagsExcludeFilter.length > 0) {
                params.tags_exclude = JSON.stringify(values.tagsExcludeFilter)
            }
            if (values.searchQuery) {
                params.search = values.searchQuery
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
        clearActiveView: () => {
            // Once detached there's no view to fall back to, so a later param-less
            // navigation shouldn't be treated as "leaving a saved view" and reset filters.
            cache.latestViewShortId = null
        },
        applyUrlFilters: ({ filters }) => {
            cache.applyingUrlFilters = true
            cache.latestViewShortId = null
            try {
                actions.clearActiveView()
                actions.applyViewFilters({
                    ...filters,
                    ...(values.dateRangeBeforeView ?? { dateFrom: values.dateFrom, dateTo: values.dateTo }),
                })
            } finally {
                cache.applyingUrlFilters = false
            }
        },
        setCurrentPage: () => {
            actions.loadTickets()
        },
        setSearchQuery: () => {
            actions.clearActiveView()
            actions.setCurrentPage(1)
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
        setAiTriageResultFilter: () => {
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
        setTagsMatch: () => {
            actions.clearActiveView()
            actions.setCurrentPage(1)
        },
        setTagsExcludeFilter: () => {
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
        applyView: ({ view }) => {
            // Snapshot the user's own date selection the first time a view overwrites it.
            // The snapshot survives view switches and detaches (a detached view's dates
            // remain applied and persisted, so the snapshot is the only copy of the
            // user's preference) and is invalidated only by a manual date pick.
            if (!values.dateRangeBeforeView) {
                actions.setDateRangeBeforeView(values.dateFrom, values.dateTo)
            }
            actions.applyViewFilters(view.filters || {})
            actions.setActiveView(view)
        },
        loadSavedView: async ({ shortId }) => {
            // Track the view the URL currently names. Rapidly switching views leaves
            // several requests in flight; only the latest one may touch state, so a
            // slow earlier response can't clobber the view the user actually landed on.
            cache.latestViewShortId = shortId
            const inFlight: Set<string> = (cache.inFlightViewShortIds ??= new Set())
            // De-dupe the concurrent afterMount + urlToAction mount triggers for the same view.
            if (inFlight.has(shortId)) {
                return
            }
            inFlight.add(shortId)
            const teamId = teamLogic.values.currentTeamId
            try {
                const view = (await conversationsViewsRetrieve(String(teamId), shortId)) as unknown as SavedTicketView
                if (cache.latestViewShortId === shortId) {
                    actions.applyView(view)
                }
            } catch {
                if (cache.latestViewShortId === shortId) {
                    lemonToast.error('Failed to load saved view')
                    actions.applyUrlFilters(DEFAULT_TICKET_FILTERS)
                }
            } finally {
                inFlight.delete(shortId)
            }
        },
        resetFilters: () => {
            const dateRangeBeforeView = values.dateRangeBeforeView
            actions.clearActiveView()
            actions.applyViewFilters({
                ...DEFAULT_TICKET_FILTERS,
                ...(dateRangeBeforeView ?? { dateFrom: null, dateTo: null }),
            })
        },
        clearFiltersKeepingSearch: () => {
            // Reset every filter to its default but keep the current search text, so the
            // user can rerun the same search unconstrained (date range included → all time).
            actions.clearActiveView()
            actions.applyViewFilters({
                ...DEFAULT_TICKET_FILTERS,
                search: values.searchQuery,
                dateFrom: null,
                dateTo: null,
            })
        },
        bulkUpdateStatus: async ({ ids, status }) => {
            actions.setBulkUpdating(true)
            try {
                const result = await api.conversationsTickets.bulkUpdateStatus(ids, status)
                lemonToast.success(`Updated ${result.updated} ticket${result.updated === 1 ? '' : 's'}`)
                actions.clearSelectedTickets()
                actions.loadTickets()
            } catch {
                lemonToast.error('Failed to update tickets')
            } finally {
                actions.setBulkUpdating(false)
            }
        },
    })),
    actionToUrl(({ values, props, cache }) => {
        const buildUrl = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] | undefined => {
            if (cache.applyingUrlFilters) {
                return
            }
            const searchParams = { ...router.values.searchParams }
            // Embedded instances (e.g. the person side panel) must never touch the page URL.
            if (props.distinctIds?.length) {
                return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
            }
            for (const paramKey of FILTER_URL_PARAM_KEYS) {
                delete searchParams[paramKey]
            }
            delete searchParams.search
            delete searchParams.view
            if (values.activeView) {
                // A saved view is a compact stand-in for its filters.
                searchParams.view = values.activeView.short_id
            } else {
                Object.assign(searchParams, filtersToUrlParams(values.currentFilters))
            }
            // Only URL changes we didn't originate should re-apply filters. Flag our own
            // writes so urlToAction skips them; re-applying a URL we just wrote resets any
            // state absent from it — e.g. the sort order while detaching a saved view.
            if (!objectsEqual(searchParams, router.values.searchParams)) {
                cache.selfNavigating = true
            }
            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
        }
        return {
            setStatusFilter: buildUrl,
            setPriorityFilter: buildUrl,
            setChannelFilter: buildUrl,
            setSlaFilter: buildUrl,
            setAiTriageResultFilter: buildUrl,
            setAssigneeFilter: buildUrl,
            setTagsFilter: buildUrl,
            setTagsMatch: buildUrl,
            setTagsExcludeFilter: buildUrl,
            setSorting: buildUrl,
            setSearchQuery: buildUrl,
            applyViewFilters: buildUrl,
            applyUrlFilters: buildUrl,
            setActiveView: buildUrl,
            clearActiveView: buildUrl,
        }
    }),
    urlToAction(({ actions, values, props, cache }) => ({
        '/support/tickets': (_, searchParams) => {
            if (props.distinctIds?.length) {
                return
            }
            // A URL change we wrote ourselves already matches state — re-applying it would
            // clobber filters not encoded in the URL. External navigations don't set this.
            if (cache.selfNavigating) {
                cache.selfNavigating = false
                return
            }
            if (searchParams.search !== undefined) {
                const sanitizedSearchParams = { ...searchParams }
                delete sanitizedSearchParams.search
                router.actions.replace(router.values.location.pathname, sanitizedSearchParams, router.values.hashParams)
                return
            }
            if (searchParams.view) {
                if (values.activeView?.short_id !== searchParams.view) {
                    actions.loadSavedView(String(searchParams.view))
                }
                return
            }
            const leavingSavedView = !!values.activeView || !!cache.latestViewShortId
            if (
                leavingSavedView ||
                (hasFilterParams(searchParams) && !urlFiltersMatchState(searchParams, values.currentFilters))
            ) {
                actions.applyUrlFilters(urlParamsToFilters(searchParams))
            }
        },
    })),
    afterMount(({ actions, values, props }) => {
        const embedded = !!props.distinctIds?.length
        const { searchParams } = router.values
        if (!embedded && searchParams.view) {
            actions.loadSavedView(String(searchParams.view))
            return
        }
        if (!embedded) {
            if (hasFilterParams(searchParams)) {
                if (!urlFiltersMatchState(searchParams, values.currentFilters)) {
                    // A shared/bookmarked link overrides the persisted selection.
                    actions.applyUrlFilters(urlParamsToFilters(searchParams))
                    return
                }
            } else {
                // No filters in the URL — reflect the persisted selection so the page is shareable on open.
                const currentFilterParams = filtersToUrlParams(values.currentFilters)
                if (Object.keys(currentFilterParams).length > 0) {
                    router.actions.replace(router.values.location.pathname, {
                        ...searchParams,
                        ...currentFilterParams,
                    })
                }
            }
        }
        actions.loadTickets()
    }),
])
