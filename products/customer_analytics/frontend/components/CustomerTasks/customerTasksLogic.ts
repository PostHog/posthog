import {
    MakeLogicType,
    LogicWrapper,
    actions,
    afterMount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast, type PaginationManual, type Sorting } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api-error'
import { trackedActionToUrl } from 'lib/logic/scenes/trackedActionToUrl'
import { objectsEqual } from 'lib/utils/objects'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { UserType } from '~/types'

import {
    accountsList,
    accountsRetrieve,
    customerTasksArchiveCreate,
    customerTasksCreate,
    customerTasksList,
    customerTasksRetrieve,
    customerTasksPartialUpdate,
    customerTasksRestoreCreate,
} from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountApi,
    CustomerTaskApi,
    CustomerTaskCreateApi,
    CustomerTaskPageApi,
    CustomerTaskUserApi,
    PaginatedAccountListApi,
    PatchedCustomerTaskUpdateApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import {
    CUSTOMER_TASK_FILTER_URL_KEYS,
    CUSTOMER_TASK_URL_KEYS,
    customerTaskSearchParams,
    CustomerTaskEvents,
    customerTasksQuery,
    DEFAULT_CUSTOMER_TASK_ORDERING,
    defaultCustomerTaskFilters,
    hasCustomerTaskFilters,
    parseCustomerTaskSearchParams,
    type CustomerTaskAccountFilter,
    type CustomerTaskFilters,
    type CustomerTaskOrdering,
    type CustomerTasksContext,
    type CustomerTaskUrlState,
    customerTaskOrderingToSorting,
    customerTaskSortingToOrdering,
} from './customerTaskFilters'

const ACCOUNT_PAGE_SIZE = 20
const INBOX_PAGE_SIZE = 50
const ACCOUNT_OPTIONS_LIMIT = 50

export interface CustomerTasksLogicProps {
    context: CustomerTasksContext
    accountId?: string
    canViewAll?: boolean
    persistPrefix?: string
}
export interface customerTasksLogicValues {
    accountOptions: AccountApi[]
    accountOptionsResponse: PaginatedAccountListApi | null
    accountOptionsResponseLoading: boolean
    accountFilterOpen: boolean
    currentTeamId: number | null
    filters: CustomerTaskFilters
    hasActiveFilters: boolean
    modalOpen: boolean
    modalTask: CustomerTaskApi | null
    mutationKeys: Record<string, boolean>
    ordering: CustomerTaskOrdering
    page: number
    pageSize: number
    pagination: PaginationManual
    taskPage: CustomerTaskPageApi | null
    taskPageError: unknown
    taskPageLoading: boolean
    taskSorting: Sorting
    tasks: CustomerTaskApi[]
    timezone: string
    draftName: string
    draftDescription: string
    draftAccount: CustomerTaskAccountFilter | null
    draftAssignedTo: CustomerTaskUserApi | null
    draftDueAt: string | null
    user: UserType | null
}
export interface customerTasksLogicActions {
    openTaskFromUrl: (taskId: string) => { taskId: string }
    closeModal: () => void
    createTask: (task: CustomerTaskCreateApi) => { task: CustomerTaskCreateApi }
    loadAccountOptions: (payload: { query: string }) => { query: string }
    loadTaskPage: () => { value: true }
    mutationFinished: (key: string) => { key: string }
    mutationStarted: (key: string) => { key: string }
    openCreateModal: () => void
    openEditModal: (task: CustomerTaskApi) => { task: CustomerTaskApi }
    resetFilters: () => void
    restoreTask: (taskId: string) => { taskId: string }
    archiveTask: (taskId: string) => { taskId: string }
    setAccountFilter: (account: CustomerTaskAccountFilter | null) => { account: CustomerTaskAccountFilter | null }
    setAccountFilterOpen: (open: boolean) => { open: boolean }
    setFilters: (filters: Partial<CustomerTaskFilters>) => { filters: Partial<CustomerTaskFilters> }
    setFiltersFromUrl: (state: CustomerTaskUrlState) => { state: CustomerTaskUrlState }
    setAccountFilterName: (name: string) => { name: string }
    setTaskOrdering: (ordering: CustomerTaskOrdering) => { ordering: CustomerTaskOrdering }
    setTaskSorting: (sorting: Sorting | null) => { sorting: Sorting | null }
    setPage: (page: number) => { page: number }
    setSearch: (search: string) => { search: string }
    setDraftAccount: (account: CustomerTaskAccountFilter | null) => { account: CustomerTaskAccountFilter | null }
    setDraftAssignedTo: (assignedTo: CustomerTaskUserApi | null) => { assignedTo: CustomerTaskUserApi | null }
    setDraftDescription: (description: string) => { description: string }
    setDraftDueAt: (dueAt: string | null) => { dueAt: string | null }
    setDraftName: (name: string) => { name: string }
    submitModal: () => void
    updateTask: (
        taskId: string,
        patch: PatchedCustomerTaskUpdateApi
    ) => { taskId: string; patch: PatchedCustomerTaskUpdateApi }
}
export type customerTasksLogicType = MakeLogicType<
    customerTasksLogicValues,
    customerTasksLogicActions,
    CustomerTasksLogicProps
>

function taskUrlState(values: customerTasksLogicValues): CustomerTaskUrlState {
    return { filters: values.filters, ordering: values.ordering, page: values.page }
}

// A rejected task write answers with the message a person needs, either as `detail` or against the
// field at fault, so show that instead of asking for a retry the server will refuse again.
function taskWriteFailureMessage(error: unknown, fallback: string): string {
    if (error instanceof ApiError) {
        const body = error.data as Record<string, unknown> | null | undefined
        for (const candidate of [error.detail, body?.assigned_to_id, body?.status]) {
            if (typeof candidate === 'string' && candidate.trim()) {
                return candidate
            }
        }
    }
    return fallback
}

export const customerTasksLogic: LogicWrapper<customerTasksLogicType> = kea<customerTasksLogicType>([
    props({} as CustomerTasksLogicProps),
    key((p) => 'customer-tasks-' + p.context + '-' + (p.accountId ?? p.persistPrefix ?? 'all')),
    path(['products', 'customer_analytics', 'frontend', 'components', 'CustomerTasks', 'customerTasksLogic']),
    connect(() => ({ values: [teamLogic, ['currentTeamId', 'timezone'], userLogic, ['user']] })),
    actions({
        openTaskFromUrl: (taskId: string) => ({ taskId }),
        loadTaskPage: true,
        loadAccountOptions: (payload: { query: string }) => payload,
        setFilters: (filters: Partial<CustomerTaskFilters>) => ({ filters }),
        setFiltersFromUrl: (state: CustomerTaskUrlState) => ({ state }),
        setAccountFilterName: (name: string) => ({ name }),
        setTaskOrdering: (ordering: CustomerTaskOrdering) => ({ ordering }),
        setTaskSorting: (sorting: Sorting | null) => ({ sorting }),
        setSearch: (search: string) => ({ search }),
        setAccountFilter: (account: CustomerTaskAccountFilter | null) => ({ account }),
        setAccountFilterOpen: (open: boolean) => ({ open }),
        setPage: (page: number) => ({ page }),
        resetFilters: () => ({}),
        openCreateModal: () => ({}),
        openEditModal: (task: CustomerTaskApi) => ({ task }),
        closeModal: () => ({}),
        setDraftName: (name: string) => ({ name }),
        setDraftDescription: (description: string) => ({ description }),
        setDraftAccount: (account: CustomerTaskAccountFilter | null) => ({ account }),
        setDraftAssignedTo: (assignedTo: CustomerTaskUserApi | null) => ({ assignedTo }),
        setDraftDueAt: (dueAt: string | null) => ({ dueAt }),
        submitModal: () => ({}),
        createTask: (task: CustomerTaskCreateApi) => ({ task }),
        updateTask: (taskId: string, patch: PatchedCustomerTaskUpdateApi) => ({ taskId, patch }),
        archiveTask: (taskId: string) => ({ taskId }),
        restoreTask: (taskId: string) => ({ taskId }),
        mutationStarted: (key: string) => ({ key }),
        mutationFinished: (key: string) => ({ key }),
    }),
    loaders(({ props, values }) => ({
        taskPage: [
            null as CustomerTaskPageApi | null,
            {
                loadTaskPage: async (_, breakpoint) => {
                    await breakpoint(250)
                    if (values.currentTeamId === null) {
                        return null
                    }
                    const result = await customerTasksList(
                        String(values.currentTeamId),
                        customerTasksQuery(
                            values.filters,
                            props.context,
                            props.accountId,
                            values.page,
                            values.pageSize,
                            values.timezone,
                            props.canViewAll,
                            values.ordering
                        )
                    )
                    breakpoint()
                    return result
                },
            },
        ],
        accountOptionsResponse: [
            null as PaginatedAccountListApi | null,
            {
                loadAccountOptions: async ({ query }: { query: string }, breakpoint) => {
                    await breakpoint(300)
                    if (values.currentTeamId === null) {
                        return null
                    }
                    const result = await accountsList(String(values.currentTeamId), {
                        search: query || undefined,
                        limit: ACCOUNT_OPTIONS_LIMIT,
                    })
                    breakpoint()
                    return result
                },
            },
        ],
    })),
    reducers(({ props }) => {
        const persist =
            props.context === 'inbox' && props.persistPrefix ? { persist: true, prefix: props.persistPrefix } : {}
        return {
            filters: [
                defaultCustomerTaskFilters(props.context),
                persist,
                {
                    setFilters: (s: CustomerTaskFilters, a: { filters: Partial<CustomerTaskFilters> }) => ({
                        ...s,
                        ...a.filters,
                    }),
                    setSearch: (s: CustomerTaskFilters, a: { search: string }) => ({ ...s, search: a.search }),
                    setAccountFilter: (s: CustomerTaskFilters, a: { account: CustomerTaskAccountFilter | null }) => ({
                        ...s,
                        account: a.account,
                    }),
                    setAccountFilterName: (s: CustomerTaskFilters, a: { name: string }) =>
                        s.account ? { ...s, account: { ...s.account, name: a.name } } : s,
                    setFiltersFromUrl: (_: CustomerTaskFilters, a: { state: CustomerTaskUrlState }) => a.state.filters,
                    resetFilters: () => defaultCustomerTaskFilters(props.context),
                },
            ],
            ordering: [
                DEFAULT_CUSTOMER_TASK_ORDERING,
                {
                    setTaskOrdering: (_, { ordering }) => ordering,
                    setFiltersFromUrl: (_: CustomerTaskOrdering, a: { state: CustomerTaskUrlState }) =>
                        a.state.ordering,
                },
            ],
            page: [
                1,
                {
                    setPage: (_: number, a: { page: number }) => a.page,
                    setFiltersFromUrl: (_: number, a: { state: CustomerTaskUrlState }) => a.state.page,
                    setFilters: () => 1,
                    setSearch: () => 1,
                    setAccountFilter: () => 1,
                    resetFilters: () => 1,
                    setTaskOrdering: () => 1,
                },
            ],
            accountFilterOpen: [false, { setAccountFilterOpen: (_, { open }) => open }],
            mutationKeys: [
                {} as Record<string, boolean>,
                {
                    mutationStarted: (s: Record<string, boolean>, a: { key: string }) => ({ ...s, [a.key]: true }),
                    mutationFinished: (s: Record<string, boolean>, a: { key: string }) => {
                        const n = { ...s }
                        delete n[a.key]
                        return n
                    },
                },
            ],
            modalOpen: [
                false,
                {
                    openCreateModal: () => true,
                    openEditModal: () => true,
                    closeModal: () => false,
                },
            ],
            modalTask: [
                null as CustomerTaskApi | null,
                {
                    openCreateModal: () => null,
                    openEditModal: (_: CustomerTaskApi | null, a: { task: CustomerTaskApi }) => a.task,
                    closeModal: () => null,
                },
            ],
            draftName: [
                '',
                {
                    openCreateModal: () => '',
                    openEditModal: (_: string, a: { task: CustomerTaskApi }) => a.task.name,
                    setDraftName: (_: string, a: { name: string }) => a.name,
                    closeModal: () => '',
                },
            ],
            draftDescription: [
                '',
                {
                    openCreateModal: () => '',
                    openEditModal: (_: string, a: { task: CustomerTaskApi }) => a.task.description ?? '',
                    setDraftDescription: (_: string, a: { description: string }) => a.description,
                    closeModal: () => '',
                },
            ],
            draftAccount: [
                null as CustomerTaskAccountFilter | null,
                {
                    openCreateModal: () => null,
                    openEditModal: (_: CustomerTaskAccountFilter | null, a: { task: CustomerTaskApi }) =>
                        a.task.account,
                    setDraftAccount: (
                        _: CustomerTaskAccountFilter | null,
                        a: { account: CustomerTaskAccountFilter | null }
                    ) => a.account,
                    closeModal: () => null,
                },
            ],
            draftAssignedTo: [
                null as CustomerTaskUserApi | null,
                {
                    openCreateModal: () => null,
                    openEditModal: (_: CustomerTaskUserApi | null, a: { task: CustomerTaskApi }) => a.task.assigned_to,
                    setDraftAssignedTo: (
                        _: CustomerTaskUserApi | null,
                        a: { assignedTo: CustomerTaskUserApi | null }
                    ) => a.assignedTo,
                    closeModal: () => null,
                },
            ],
            draftDueAt: [
                null as string | null,
                {
                    openCreateModal: () => null,
                    openEditModal: (_: string | null, a: { task: CustomerTaskApi }) => a.task.due_at,
                    setDraftDueAt: (_: string | null, a: { dueAt: string | null }) => a.dueAt,
                    closeModal: () => null,
                },
            ],
        }
    }),
    selectors(({ actions, props }) => ({
        tasks: [
            (s) => [s.taskPage],
            (p: CustomerTaskPageApi | null): CustomerTaskApi[] => (p?.results ? [...p.results] : []),
        ],
        accountOptions: [
            (s) => [s.accountOptionsResponse],
            (p: PaginatedAccountListApi | null): AccountApi[] => p?.results ?? [],
        ],
        hasActiveFilters: [
            (s) => [s.filters],
            (f: CustomerTaskFilters): boolean => hasCustomerTaskFilters(f, props.context),
        ],
        taskSorting: [(s) => [s.ordering], (ordering: CustomerTaskOrdering) => customerTaskOrderingToSorting(ordering)],
        pageSize: [() => [], (): number => (props.context === 'account' ? ACCOUNT_PAGE_SIZE : INBOX_PAGE_SIZE)],
        pagination: [
            (s) => [s.page, s.taskPage],
            (page: number, p: CustomerTaskPageApi | null): PaginationManual => ({
                controlled: true,
                pageSize: props.context === 'account' ? ACCOUNT_PAGE_SIZE : INBOX_PAGE_SIZE,
                currentPage: page,
                entryCount: p?.count ?? 0,
                onBackward: () => actions.setPage(page - 1),
                onForward: () => actions.setPage(page + 1),
            }),
        ],
    })),
    listeners(({ actions, props, values }) => ({
        openTaskFromUrl: async ({ taskId }, breakpoint) => {
            if (values.currentTeamId === null) {
                return
            }
            try {
                const task = await customerTasksRetrieve(String(values.currentTeamId), taskId)
                breakpoint()
                actions.openEditModal(task)
            } catch (error) {
                breakpoint()
                lemonToast.error(
                    taskWriteFailureMessage(error, 'Could not open the task. Refresh the page to try again.')
                )
            }
        },
        setFilters: () => actions.loadTaskPage(),
        setFiltersFromUrl: async () => {
            actions.loadTaskPage()
            const account = values.filters.account
            if (!account || account.name || values.currentTeamId === null) {
                return
            }
            try {
                const resolved = await accountsRetrieve(String(values.currentTeamId), account.id)
                if (values.filters.account?.id === account.id) {
                    actions.setAccountFilterName(resolved.name)
                }
            } catch {
                // The account filter still applies; the control falls back to its generic label.
            }
        },
        setSearch: () => actions.loadTaskPage(),
        setAccountFilter: () => actions.loadTaskPage(),
        setPage: () => actions.loadTaskPage(),
        setTaskOrdering: () => actions.loadTaskPage(),
        setTaskSorting: ({ sorting }) => {
            const ordering = customerTaskSortingToOrdering(sorting)
            if (ordering) {
                actions.setTaskOrdering(ordering)
            }
        },
        resetFilters: () => actions.loadTaskPage(),
        openCreateModal: () => {
            if (props.context === 'inbox' && values.filters.assignee === 'me' && values.user) {
                actions.setDraftAssignedTo({
                    id: values.user.id,
                    email: values.user.email,
                    first_name: values.user.first_name,
                    last_name: values.user.last_name ?? '',
                })
            }
        },
        submitModal: () => {
            if (values.mutationKeys.create || (values.modalTask && values.mutationKeys[values.modalTask.id])) {
                return
            }
            const accountId =
                props.context === 'account' ? (props.accountId ?? null) : (values.draftAccount?.id ?? null)
            const description = values.draftDescription || null
            const assignedToId = values.draftAssignedTo?.id ?? null
            if (values.modalTask) {
                const patch: PatchedCustomerTaskUpdateApi = {}
                if (accountId !== (values.modalTask.account?.id ?? null)) {
                    patch.account_id = accountId
                }
                if (values.draftName !== values.modalTask.name) {
                    patch.name = values.draftName
                }
                if (values.draftDescription !== (values.modalTask.description ?? '')) {
                    patch.description = description
                }
                if (assignedToId !== (values.modalTask.assigned_to?.id ?? null)) {
                    patch.assigned_to_id = assignedToId
                }
                if (values.draftDueAt !== values.modalTask.due_at) {
                    patch.due_at = values.draftDueAt
                }
                if (Object.keys(patch).length === 0) {
                    actions.closeModal()
                    return
                }
                actions.updateTask(values.modalTask.id, patch)
            } else {
                actions.createTask({
                    account_id: accountId,
                    name: values.draftName,
                    description,
                    assigned_to_id: assignedToId,
                    due_at: values.draftDueAt,
                })
            }
        },
        createTask: async ({ task }: { task: CustomerTaskCreateApi }) => {
            if (values.mutationKeys.create || !task.name.trim() || values.currentTeamId === null) {
                return
            }
            actions.mutationStarted('create')
            try {
                await customerTasksCreate(String(values.currentTeamId), { ...task, name: task.name.trim() })
                actions.mutationFinished('create')
                actions.closeModal()
                actions.loadTaskPage()
            } catch (error) {
                actions.mutationFinished('create')
                lemonToast.error(taskWriteFailureMessage(error, 'Could not create the task. Try again.'))
            }
        },
        updateTask: async ({ taskId, patch }: { taskId: string; patch: PatchedCustomerTaskUpdateApi }) => {
            const current = values.tasks.find((task) => task.id === taskId)
            if (current && (!current.can_edit || current.archived_at)) {
                return
            }
            const changed = current
                ? Object.entries(patch).some(
                      ([key, value]) =>
                          (key === 'assigned_to_id'
                              ? (current.assigned_to?.id ?? null)
                              : key === 'account_id'
                                ? (current.account?.id ?? null)
                                : current[key as keyof CustomerTaskApi]) !== value
                  )
                : true
            if (!changed || values.mutationKeys[taskId] || values.currentTeamId === null) {
                return
            }
            actions.mutationStarted(taskId)
            try {
                await customerTasksPartialUpdate(String(values.currentTeamId), taskId, patch)
                actions.mutationFinished(taskId)
                actions.closeModal()
                actions.loadTaskPage()
            } catch (error) {
                actions.mutationFinished(taskId)
                lemonToast.error(taskWriteFailureMessage(error, 'Could not save the task. Try again.'))
            }
        },
        archiveTask: async ({ taskId }: { taskId: string }) => {
            if (values.tasks.find((task) => task.id === taskId)?.can_edit === false) {
                return
            }
            if (values.mutationKeys[taskId] || values.currentTeamId === null) {
                return
            }
            actions.mutationStarted(taskId)
            try {
                await customerTasksArchiveCreate(String(values.currentTeamId), taskId)
                actions.mutationFinished(taskId)
                actions.loadTaskPage()
            } catch {
                actions.mutationFinished(taskId)
                lemonToast.error('Could not archive the task. Try again.')
            }
        },
        restoreTask: async ({ taskId }: { taskId: string }) => {
            const current = values.tasks.find((task) => task.id === taskId)
            if (current && !current.can_restore) {
                return
            }
            if (values.mutationKeys[taskId] || values.currentTeamId === null) {
                return
            }
            actions.mutationStarted(taskId)
            try {
                await customerTasksRestoreCreate(String(values.currentTeamId), taskId)
                actions.mutationFinished(taskId)
                actions.loadTaskPage()
            } catch {
                actions.mutationFinished(taskId)
                lemonToast.error('Could not restore the task. Try again.')
            }
        },
    })),
    trackedActionToUrl(({ props, values }) => {
        if (props.context !== 'inbox') {
            return {}
        }
        const toUrl = (): [string, Record<string, any>, any, { replace: boolean }] => {
            const searchParams = { ...router.values.searchParams }
            for (const key of CUSTOMER_TASK_URL_KEYS) {
                delete searchParams[key]
            }
            Object.assign(searchParams, customerTaskSearchParams(taskUrlState(values)))
            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
        }
        return {
            setFilters: toUrl,
            setSearch: toUrl,
            setAccountFilter: toUrl,
            setPage: toUrl,
            setTaskOrdering: toUrl,
            resetFilters: toUrl,
        }
    }),
    urlToAction(({ actions, props, values }) => {
        if (props.context !== 'inbox') {
            return {}
        }
        return {
            [urls.customerAnalyticsTasks()]: (_, searchParams) => {
                if (typeof searchParams.task_id === 'string' && searchParams.task_id !== values.modalTask?.id) {
                    actions.openTaskFromUrl(searchParams.task_id)
                }
                const parsed = parseCustomerTaskSearchParams(searchParams)
                // A link that names a filter decides the whole view, so its filters replace the ones
                // the person left behind. A link that only sorts or pages leaves them alone.
                const hasFiltersInUrl = CUSTOMER_TASK_FILTER_URL_KEYS.some((key) => searchParams[key] !== undefined)
                const next: CustomerTaskUrlState = {
                    filters: hasFiltersInUrl ? parsed.filters : values.filters,
                    ordering: parsed.ordering,
                    page: parsed.page,
                }
                const current = customerTaskSearchParams(taskUrlState(values))
                if (!objectsEqual(current, customerTaskSearchParams(next))) {
                    actions.setFiltersFromUrl(next)
                }
            },
        }
    }),
    afterMount(({ actions, props }) => {
        actions.loadTaskPage()
        if (props.context === 'inbox') {
            actions.loadAccountOptions({ query: '' })
            const { source, ...rest } = router.values.searchParams
            posthog.capture(CustomerTaskEvents.InboxViewed, {
                source: typeof source === 'string' ? source : null,
            })
            // Drop the source so a second visit in the same session, and any link the person copies,
            // are not attributed to whatever brought them here first.
            if (source !== undefined) {
                router.actions.replace(router.values.location.pathname, rest, router.values.hashParams)
            }
        }
    }),
])
