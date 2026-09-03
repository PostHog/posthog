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

import { lemonToast, type PaginationManual, type Sorting } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import {
    accountsList,
    customerTasksArchiveCreate,
    customerTasksCreate,
    customerTasksList,
    customerTasksPartialUpdate,
    customerTasksRestoreCreate,
} from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountApi,
    CustomerTaskApi,
    CustomerTaskCreateApi,
    CustomerTaskPageApi,
    PaginatedAccountListApi,
    PatchedCustomerTaskUpdateApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import {
    customerTasksQuery,
    DEFAULT_CUSTOMER_TASK_ORDERING,
    defaultCustomerTaskFilters,
    hasCustomerTaskFilters,
    type CustomerTaskAccountFilter,
    type CustomerTaskFilters,
    type CustomerTaskOrdering,
    type CustomerTasksContext,
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
    draftAccountId: string | null
    draftAssignedTo: number | null
    draftDueAt: string | null
}
export interface customerTasksLogicActions {
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
    setTaskOrdering: (ordering: CustomerTaskOrdering) => { ordering: CustomerTaskOrdering }
    setTaskSorting: (sorting: Sorting | null) => { sorting: Sorting | null }
    setPage: (page: number) => { page: number }
    setSearch: (search: string) => { search: string }
    setDraftAccountId: (accountId: string | null) => { accountId: string | null }
    setDraftAssignedTo: (assignedToId: number | null) => { assignedToId: number | null }
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
export const customerTasksLogic: LogicWrapper<customerTasksLogicType> = kea<customerTasksLogicType>([
    props({} as CustomerTasksLogicProps),
    key((p) => 'customer-tasks-' + p.context + '-' + (p.accountId ?? p.persistPrefix ?? 'all')),
    path(['products', 'customer_analytics', 'frontend', 'components', 'CustomerTasks', 'customerTasksLogic']),
    connect(() => ({ values: [teamLogic, ['currentTeamId', 'timezone']] })),
    actions({
        loadTaskPage: true,
        loadAccountOptions: (payload: { query: string }) => payload,
        setFilters: (filters: Partial<CustomerTaskFilters>) => ({ filters }),
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
        setDraftAccountId: (accountId: string | null) => ({ accountId }),
        setDraftAssignedTo: (assignedToId: number | null) => ({ assignedToId }),
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
                    resetFilters: () => defaultCustomerTaskFilters(props.context),
                },
            ],
            ordering: [DEFAULT_CUSTOMER_TASK_ORDERING, { setTaskOrdering: (_, { ordering }) => ordering }],
            page: [
                1,
                {
                    setPage: (_: number, a: { page: number }) => a.page,
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
                    createTask: () => false,
                },
            ],
            modalTask: [
                null as CustomerTaskApi | null,
                {
                    openCreateModal: () => null,
                    openEditModal: (_: CustomerTaskApi | null, a: { task: CustomerTaskApi }) => a.task,
                    closeModal: () => null,
                    createTask: () => null,
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
            draftAccountId: [
                props.accountId ?? null,
                {
                    openCreateModal: () => props.accountId ?? null,
                    openEditModal: (_: string | null, a: { task: CustomerTaskApi }) => a.task.account?.id ?? null,
                    setDraftAccountId: (_: string | null, a: { accountId: string | null }) => a.accountId,
                    closeModal: () => props.accountId ?? null,
                },
            ],
            draftAssignedTo: [
                null as number | null,
                {
                    openCreateModal: () => null,
                    openEditModal: (_: number | null, a: { task: CustomerTaskApi }) => a.task.assigned_to?.id ?? null,
                    setDraftAssignedTo: (_: number | null, a: { assignedToId: number | null }) => a.assignedToId,
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
    listeners(({ actions, values }) => ({
        setFilters: () => actions.loadTaskPage(),
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
        submitModal: () => {
            if (values.mutationKeys.create || (values.modalTask && values.mutationKeys[values.modalTask.id])) {
                return
            }
            if (values.modalTask) {
                actions.updateTask(values.modalTask.id, {
                    account_id: values.draftAccountId,
                    name: values.draftName,
                    description: values.draftDescription || null,
                    assigned_to_id: values.draftAssignedTo,
                    due_at: values.draftDueAt,
                })
            } else {
                actions.createTask({
                    account_id: values.draftAccountId,
                    name: values.draftName,
                    description: values.draftDescription || null,
                    assigned_to_id: values.draftAssignedTo,
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
            } catch {
                actions.mutationFinished('create')
                lemonToast.error('Could not create the task. Try again.')
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
                              : current[key as keyof CustomerTaskApi]) !== value
                  )
                : true
            if (!changed || values.mutationKeys[taskId] || values.currentTeamId === null) {
                if (!changed) {
                    actions.closeModal()
                }
                return
            }
            actions.mutationStarted(taskId)
            try {
                await customerTasksPartialUpdate(String(values.currentTeamId), taskId, patch)
                actions.mutationFinished(taskId)
                actions.closeModal()
                actions.loadTaskPage()
            } catch {
                actions.mutationFinished(taskId)
                lemonToast.error('Could not save the task. Try again.')
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
            if (values.tasks.find((task) => task.id === taskId)?.can_edit === false) {
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
    afterMount(({ actions }) => {
        actions.loadTaskPage()
        actions.loadAccountOptions({ query: String() })
    }),
])
