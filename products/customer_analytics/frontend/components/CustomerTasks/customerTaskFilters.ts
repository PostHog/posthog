import type { Sorting } from '@posthog/lemon-ui'

import { dayjs, dayjsLocalToTimezone, dayjsNowInTimezone } from 'lib/dayjs'
import { isUUIDLike } from 'lib/utils/guards'

import type {
    CustomerTaskApi,
    CustomerTaskStatusEnumApi,
    CustomerTasksListArchiveState,
    CustomerTasksListParams,
} from 'products/customer_analytics/frontend/generated/api.schemas'

export type CustomerTasksContext = 'account' | 'inbox'
export type CustomerTaskStatusFilter = 'open' | 'completed' | 'canceled' | 'all'
export type CustomerTaskAssigneeFilter = 'any' | 'me' | 'unassigned' | number
export type CustomerTaskDueFilter = 'any' | 'overdue' | 'today' | 'upcoming' | 'no_due_date'
export type CustomerTaskAccountFilter = { id: string; name: string }

const MAX_CUSTOMER_TASK_ASSIGNEE_ID = 2_147_483_647
const CUSTOMER_TASK_ORDERINGS = [
    'name',
    '-name',
    'status',
    '-status',
    'assigned_to',
    '-assigned_to',
    'due_at',
    '-due_at',
    'updated_at',
    '-updated_at',
    'account',
    '-account',
] as const satisfies readonly NonNullable<CustomerTasksListParams['ordering']>[]

export type CustomerTaskOrdering = (typeof CUSTOMER_TASK_ORDERINGS)[number]

export const DEFAULT_CUSTOMER_TASK_ORDERING: CustomerTaskOrdering = 'due_at'

export type CustomerTaskFilters = {
    search: string
    status: CustomerTaskStatusFilter
    assignee: CustomerTaskAssigneeFilter
    archiveState: CustomerTasksListArchiveState
    account: CustomerTaskAccountFilter | null
    due: CustomerTaskDueFilter
}

const CUSTOMER_TASK_SORTING: Record<CustomerTaskOrdering, Sorting> = {
    name: { columnKey: 'name', order: 1 },
    '-name': { columnKey: 'name', order: -1 },
    status: { columnKey: 'status', order: 1 },
    '-status': { columnKey: 'status', order: -1 },
    assigned_to: { columnKey: 'assigned_to', order: 1 },
    '-assigned_to': { columnKey: 'assigned_to', order: -1 },
    due_at: { columnKey: 'due_at', order: 1 },
    '-due_at': { columnKey: 'due_at', order: -1 },
    updated_at: { columnKey: 'updated_at', order: 1 },
    '-updated_at': { columnKey: 'updated_at', order: -1 },
    account: { columnKey: 'account', order: 1 },
    '-account': { columnKey: 'account', order: -1 },
}

export const CUSTOMER_TASK_STATUS_OPTIONS: readonly { value: CustomerTaskStatusFilter; label: string }[] = [
    { value: 'open', label: 'Open' },
    { value: 'completed', label: 'Completed' },
    { value: 'canceled', label: 'Canceled' },
    { value: 'all', label: 'All' },
]
export const CUSTOMER_TASK_ARCHIVE_OPTIONS: readonly { value: CustomerTasksListArchiveState; label: string }[] = [
    { value: 'active', label: 'Active' },
    { value: 'archived', label: 'Archived' },
    { value: 'all', label: 'All' },
]
export const CUSTOMER_TASK_DUE_OPTIONS: readonly { value: CustomerTaskDueFilter; label: string }[] = [
    { value: 'any', label: 'Any time' },
    { value: 'overdue', label: 'Overdue' },
    { value: 'today', label: 'Today' },
    { value: 'upcoming', label: 'Upcoming' },
    { value: 'no_due_date', label: 'No due date' },
]
export const CUSTOMER_TASK_STATUS_TRANSITIONS: Readonly<
    Record<CustomerTaskStatusEnumApi, readonly CustomerTaskStatusEnumApi[]>
> = {
    open: ['in_progress', 'completed', 'canceled'],
    in_progress: ['open', 'completed', 'canceled'],
    completed: ['open'],
    canceled: ['open'],
}

// The API refuses to update an archived task, so every write control shares this reason.
export function customerTaskEditDisabledReason(task: CustomerTaskApi): string | undefined {
    if (task.archived_at) {
        return 'Restore this task to edit it'
    }
    if (!task.can_edit) {
        return 'You cannot edit this task'
    }
    return undefined
}

export function customerTaskOrderingToSorting(ordering: CustomerTaskOrdering): Sorting {
    return CUSTOMER_TASK_SORTING[ordering]
}

export function customerTaskSortingToOrdering(sorting: Sorting | null): CustomerTaskOrdering | null {
    if (!sorting) {
        return null
    }
    switch (sorting.columnKey) {
        case 'name':
            return sorting.order === -1 ? '-name' : 'name'
        case 'status':
            return sorting.order === -1 ? '-status' : 'status'
        case 'assigned_to':
            return sorting.order === -1 ? '-assigned_to' : 'assigned_to'
        case 'due_at':
            return sorting.order === -1 ? '-due_at' : 'due_at'
        case 'updated_at':
            return sorting.order === -1 ? '-updated_at' : 'updated_at'
        case 'account':
            return sorting.order === -1 ? '-account' : 'account'
        default:
            return null
    }
}

export function defaultCustomerTaskFilters(context: CustomerTasksContext): CustomerTaskFilters {
    return {
        search: '',
        status: 'open',
        assignee: context === 'inbox' ? 'me' : 'any',
        archiveState: 'active',
        account: null,
        due: 'any',
    }
}
export function hasCustomerTaskFilters(filters: CustomerTaskFilters, context: CustomerTasksContext): boolean {
    const defaults = defaultCustomerTaskFilters(context)
    return JSON.stringify(filters) !== JSON.stringify(defaults)
}
export function customerTaskDueBounds(
    due: CustomerTaskDueFilter,
    timezone: string,
    now?: string
): Pick<CustomerTasksListParams, 'due_after' | 'due_before' | 'has_due_at'> {
    if (due === 'any') {
        return {}
    }
    if (due === 'no_due_date') {
        return { has_due_at: false }
    }
    const current = now ? dayjs(now).tz(timezone) : dayjsNowInTimezone(timezone)
    const currentInstant = now ? dayjs(now) : dayjsNowInTimezone(timezone).tz(timezone, true)
    if (due === 'overdue') {
        return { due_before: currentInstant.toISOString() }
    }
    if (due === 'upcoming') {
        return { due_after: currentInstant.toISOString() }
    }
    const start = current.startOf('day').format('YYYY-MM-DDTHH:mm:ss.SSS')
    const end = current.add(1, 'day').startOf('day').format('YYYY-MM-DDTHH:mm:ss.SSS')
    return {
        due_after: dayjsLocalToTimezone(start, timezone).toISOString(),
        due_before: dayjsLocalToTimezone(end, timezone).toISOString(),
    }
}
export function customerTasksQuery(
    filters: CustomerTaskFilters,
    context: CustomerTasksContext,
    accountId: string | undefined,
    page: number,
    pageSize: number,
    timezone: string,
    canViewAll = true,
    ordering: CustomerTaskOrdering = DEFAULT_CUSTOMER_TASK_ORDERING
): CustomerTasksListParams {
    const query: CustomerTasksListParams = {
        search: filters.search || undefined,
        account_id: accountId ?? filters.account?.id,
        assigned_to:
            !canViewAll && context === 'inbox'
                ? 'me'
                : filters.assignee === 'any'
                  ? undefined
                  : filters.assignee === 'me'
                    ? 'me'
                    : filters.assignee === 'unassigned'
                      ? 'unassigned'
                      : String(filters.assignee),
        statuses:
            filters.status === 'all' ? undefined : filters.status === 'open' ? 'open,in_progress' : filters.status,
        archive_state: filters.archiveState,
        ordering,
        limit: pageSize,
        offset: (page - 1) * pageSize,
        ...customerTaskDueBounds(filters.due, timezone),
    }
    if (context === 'account') {
        delete query.due_after
        delete query.due_before
        delete query.has_due_at
    }
    return query
}

export const CUSTOMER_TASK_FILTER_URL_KEYS = ['search', 'status', 'assignee', 'archive', 'due', 'account'] as const

export const CUSTOMER_TASK_URL_KEYS = [...CUSTOMER_TASK_FILTER_URL_KEYS, 'sort', 'page'] as const

// Event names are consumed by product analytics, so changing one splits its historical data.
export const CustomerTaskEvents = {
    InboxViewed: 'customer analytics tasks inbox viewed',
} as const

export type CustomerTaskUrlState = {
    filters: CustomerTaskFilters
    ordering: CustomerTaskOrdering
    page: number
}

// The inbox keeps `overdue` and `today` symbolic in the link so customerTaskDueBounds resolves them
// against the project timezone when the page opens, not when the link was written.
export function customerTaskSearchParams(state: CustomerTaskUrlState): Record<string, string> {
    const defaults = defaultCustomerTaskFilters('inbox')
    const params: Record<string, string> = {}
    if (state.filters.search) {
        params.search = state.filters.search
    }
    if (state.filters.status !== defaults.status) {
        params.status = state.filters.status
    }
    if (state.filters.assignee !== defaults.assignee) {
        params.assignee = String(state.filters.assignee)
    }
    if (state.filters.archiveState !== defaults.archiveState) {
        params.archive = state.filters.archiveState
    }
    if (state.filters.due !== defaults.due) {
        params.due = state.filters.due
    }
    if (state.filters.account) {
        params.account = state.filters.account.id
    }
    if (state.ordering !== DEFAULT_CUSTOMER_TASK_ORDERING) {
        params.sort = state.ordering
    }
    if (state.page > 1) {
        params.page = String(state.page)
    }
    return params
}

function parseAssignee(value: unknown): CustomerTaskAssigneeFilter | null {
    if (value === 'any' || value === 'me' || value === 'unassigned') {
        return value
    }
    const memberId = Number(value)
    return Number.isInteger(memberId) && memberId > 0 && memberId <= MAX_CUSTOMER_TASK_ASSIGNEE_ID ? memberId : null
}

function parseOneOf<T extends string>(value: unknown, allowed: readonly T[]): T | null {
    return allowed.some((candidate) => candidate === value) ? (value as T) : null
}

function parseOption<T extends string>(value: unknown, options: readonly { value: T }[]): T | null {
    return parseOneOf(
        value,
        options.map((option) => option.value)
    )
}

// A link only carries the account id, so the name stays empty until the logic resolves it.
export function parseCustomerTaskSearchParams(searchParams: Record<string, any>): CustomerTaskUrlState {
    const defaults = defaultCustomerTaskFilters('inbox')
    const page = Number(searchParams.page)
    return {
        filters: {
            // The router parses a purely numeric query param into a number, so `?search=123` arrives
            // as 123. A string check would drop it and the link would show an unfiltered list.
            search: searchParams.search != null ? String(searchParams.search) : '',
            status: parseOption(searchParams.status, CUSTOMER_TASK_STATUS_OPTIONS) ?? defaults.status,
            assignee: parseAssignee(searchParams.assignee) ?? defaults.assignee,
            archiveState: parseOption(searchParams.archive, CUSTOMER_TASK_ARCHIVE_OPTIONS) ?? defaults.archiveState,
            account:
                typeof searchParams.account === 'string' && isUUIDLike(searchParams.account)
                    ? { id: searchParams.account, name: '' }
                    : null,
            due: parseOption(searchParams.due, CUSTOMER_TASK_DUE_OPTIONS) ?? defaults.due,
        },
        ordering: parseOneOf(searchParams.sort, CUSTOMER_TASK_ORDERINGS) ?? DEFAULT_CUSTOMER_TASK_ORDERING,
        page: Number.isInteger(page) && page > 0 ? page : 1,
    }
}

export function customerTasksPersistencePrefix(teamId: number, userId: number): string {
    return `${teamId}_${userId}_customer_analytics_tasks__`
}
