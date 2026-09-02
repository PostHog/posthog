import { dayjs, dayjsLocalToTimezone, dayjsNowInTimezone } from 'lib/dayjs'

import type {
    CustomerTasksListParams,
    CustomerTasksListArchiveState,
    CustomerTaskStatusEnumApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

export type CustomerTasksContext = 'account' | 'inbox'
export type CustomerTaskStatusFilter = 'open' | 'completed' | 'canceled' | 'all'
export type CustomerTaskAssigneeFilter = 'any' | 'me' | 'unassigned' | number
export type CustomerTaskDueFilter = 'any' | 'overdue' | 'today' | 'upcoming' | 'no_due_date'
export type CustomerTaskAccountFilter = { id: string; name: string }
export type CustomerTaskFilters = {
    search: string
    status: CustomerTaskStatusFilter
    assignee: CustomerTaskAssigneeFilter
    archiveState: CustomerTasksListArchiveState
    account: CustomerTaskAccountFilter | null
    due: CustomerTaskDueFilter
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
    timezone: string
): CustomerTasksListParams {
    const query: CustomerTasksListParams = {
        search: filters.search || undefined,
        account_id: accountId ?? filters.account?.id,
        assigned_to:
            filters.assignee === 'any'
                ? undefined
                : filters.assignee === 'me'
                  ? 'me'
                  : filters.assignee === 'unassigned'
                    ? 'unassigned'
                    : String(filters.assignee),
        statuses:
            filters.status === 'all' ? undefined : filters.status === 'open' ? 'open,in_progress' : filters.status,
        archive_state: filters.archiveState,
        ordering: 'due_at',
        limit: pageSize,
        offset: (page - 1) * pageSize,
        ...customerTaskDueBounds(filters.due, timezone),
    }
    if (context === 'account') {
        delete query.assigned_to
        delete query.due_after
        delete query.due_before
        delete query.has_due_at
    }
    return query
}

export function customerTasksPersistencePrefix(teamId: number, userId: number): string {
    return `${teamId}_${userId}_customer_analytics_tasks__`
}
