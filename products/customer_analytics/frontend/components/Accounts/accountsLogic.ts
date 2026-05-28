import { actions, afterMount, connect, isBreakpoint, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AccountsQuery,
    DatabaseSchemaField,
    DatabaseSchemaTable,
    DataTableNode,
    NodeKind,
} from '~/queries/schema/schema-general'
import type { DataWarehouseViewLink, UserBasicType } from '~/types'

import { accountsList, accountsPartialUpdate } from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountApi,
    PatchedAccountApiProperties,
} from 'products/customer_analytics/frontend/generated/api.schemas'
import { joinsLogic } from 'products/data_warehouse/frontend/shared/logics/joinsLogic'

import { extractDisplayLabel } from '~/queries/nodes/DataTable/utils'

import { CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS } from '../../constants'
import type { accountsLogicType } from './accountsLogicType'

export const ACCOUNTS_PAGE_SIZE = 20

export const ACCOUNTS_HOGQL_DATA_NODE_KEY = 'customer-analytics-accounts-hogql'

// Columns aliased into the `context.columns.X` namespace are always included in the
// SELECT — the table cell renderers depend on them for row identity (id) and the
// external_id display in the Account cell, but they're hidden from the visible
// columns via QueryContextColumn.hidden = true.
export const ACCOUNTS_HOGQL_PINNED_SELECT: string[] = [
    'id AS `context.columns.id`',
    'external_id AS `context.columns.external_id`',
]

// User-configurable defaults — the shape the table ships with out of the box.
export const ACCOUNTS_HOGQL_DEFAULT_SELECT: string[] = [
    'name',
    'accounts.tags.names AS tag_names',
    'accounts.notebooks.count AS notebook_count',
    'csm',
    'account_executive',
    'account_owner',
]

export const ACCOUNTS_COLUMN_CONFIG_KEY = 'customer_analytics_accounts_columns'

// `allTablesMap` keys system tables by their fully qualified name (e.g.
// `system.accounts`), matching `resolve_visible_table_names()` on the backend.
export const ACCOUNTS_ACCOUNTS_TABLE_NAME = 'system.accounts'

// The data-warehouse-join API normalizes source_table_name via
// `table.to_printed_hogql()` which, for system PostgresTables, returns the
// unqualified name. Compare against both forms so we catch joins regardless
// of which name the backend hands us.
const ACCOUNTS_JOIN_SOURCE_TABLE_NAMES = new Set(['accounts', ACCOUNTS_ACCOUNTS_TABLE_NAME])

export type AccountColumnGroupKey = 'account_properties' | 'sql_expression' | `accounts.${string}`

export type AccountColumnOption = {
    name: string
    expression: string
    type?: string
}

export type AccountColumnGroup = {
    key: AccountColumnGroupKey
    label: string
    options: AccountColumnOption[]
    isFreeform?: boolean
}

// Field types that point at joined tables/views (lazy joins, virtual tables,
// user-defined data warehouse joins, saved queries). Each one surfaces as a
// dedicated dropdown entry in the column configurator.
const JOIN_FIELD_TYPES = new Set(['lazy_table', 'virtual_table', 'view', 'materialized_view'])

// Field types we omit from the "Account properties" group — these are
// navigation aliases, joined tables (handled separately), or unknown types.
const SKIPPED_DIRECT_FIELD_TYPES = new Set([
    'lazy_table',
    'virtual_table',
    'view',
    'materialized_view',
    'field_traverser',
    'unknown',
])

function buildJoinOptions(
    fieldName: string,
    fields: string[],
    joinedTable: DatabaseSchemaTable | undefined
): AccountColumnOption[] {
    return fields.map((name) => ({
        name,
        // `accounts.<join>.<col> AS <col>` — alias keeps the visible column
        // name human-readable while disambiguating columns that collide with
        // direct fields (e.g. `name` on a joined table).
        expression: `accounts.${fieldName}.${name} AS ${name}`,
        type: joinedTable?.fields?.[name]?.type,
    }))
}

function joinOptionsFromSchema(
    field: DatabaseSchemaField,
    joinedTable: DatabaseSchemaTable | undefined
): AccountColumnOption[] {
    const names: string[] = field.fields ?? Object.keys(joinedTable?.fields ?? {})
    return buildJoinOptions(field.name, names, joinedTable)
}

export function buildAccountColumnGroups(
    allTablesMap: Record<string, DatabaseSchemaTable> | null | undefined,
    warehouseJoins: DataWarehouseViewLink[]
): AccountColumnGroup[] {
    const accountsTable = allTablesMap?.[ACCOUNTS_ACCOUNTS_TABLE_NAME]
    const directOptions: AccountColumnOption[] = []
    const joinGroups: AccountColumnGroup[] = []
    const seenJoinKeys = new Set<string>()

    const addJoinGroup = (
        fieldName: string,
        joinedTable: DatabaseSchemaTable | undefined,
        options: AccountColumnOption[]
    ): void => {
        const key = `accounts.${fieldName}` as AccountColumnGroupKey
        if (seenJoinKeys.has(key)) {
            return
        }
        seenJoinKeys.add(key)
        joinGroups.push({ key, label: key, options })
    }

    if (accountsTable) {
        for (const field of Object.values(accountsTable.fields)) {
            if (JOIN_FIELD_TYPES.has(field.type)) {
                const joinedTable = field.table ? allTablesMap?.[field.table] : undefined
                addJoinGroup(field.name, joinedTable, joinOptionsFromSchema(field, joinedTable))
                continue
            }
            if (SKIPPED_DIRECT_FIELD_TYPES.has(field.type)) {
                continue
            }
            directOptions.push({
                name: field.name,
                expression: field.hogql_value || field.name,
                type: field.type,
            })
        }
    }

    // Data-warehouse joins targeting `system.accounts` are returned in the
    // separate `joins` array on the schema response (loaded by `joinsLogic`),
    // not inside the source table's `fields`. Surface them as additional
    // first-class column groups so users don't have to drop to SQL.
    for (const join of warehouseJoins) {
        if (
            !join.source_table_name ||
            !ACCOUNTS_JOIN_SOURCE_TABLE_NAMES.has(join.source_table_name) ||
            !join.field_name ||
            !join.joining_table_name
        ) {
            continue
        }
        const joinedTable = allTablesMap?.[join.joining_table_name]
        if (!joinedTable) {
            continue
        }
        const columnNames = Object.keys(joinedTable.fields)
        addJoinGroup(join.field_name, joinedTable, buildJoinOptions(join.field_name, columnNames, joinedTable))
    }

    return [
        { key: 'account_properties', label: 'Account properties', options: directOptions },
        ...joinGroups,
        { key: 'sql_expression', label: 'SQL expression', options: [], isFreeform: true },
    ]
}

interface SortLikeValues {
    sortOrder: AccountSortOrder
    visibleColumnNames: string[]
}

interface SortLikeActions {
    setSortOrder: (sortOrder: AccountSortOrder) => void
}

// Sort safety: if the user removes the column currently being sorted on, drop
// the sort — otherwise the backend receives an `orderBy` that references a
// non-existent alias.
function clearSortIfColumnRemoved(values: SortLikeValues, actions: SortLikeActions): void {
    const sort = values.sortOrder
    if (!sort) {
        return
    }
    if (!values.visibleColumnNames.includes(sort.column)) {
        actions.setSortOrder(null)
    }
}

export type RoleFilterValue = number | null

export type AccountsView = 'endpoint' | 'hogql'

export type AccountRoleKey = 'csm' | 'account_executive' | 'account_owner'

export type AccountSortableColumn = 'notebook_count' | 'csm' | 'account_executive'

export type AccountSortDirection = 'asc' | 'desc'

export type AccountSortOrder = { column: AccountSortableColumn; direction: AccountSortDirection } | null

// Maps a sortable column key to the HogQL expression to use in ORDER BY.
// `notebook_count` is the aliased integer count from the SELECT.
// `csm` and `account_executive` are tuples — sorting by `tupleElement(t, 2)` orders
// by the `email` field so the result matches what the user sees on screen.
export const ACCOUNTS_HOGQL_SORT_EXPRS: Record<AccountSortableColumn, string> = {
    notebook_count: 'notebook_count',
    csm: 'tupleElement(csm, 2)',
    account_executive: 'tupleElement(account_executive, 2)',
}

const ROLE_LABELS: Record<AccountRoleKey, string> = {
    csm: 'CSM',
    account_executive: 'Account executive',
    account_owner: 'Account owner',
}

export const savingRoleKey = (accountId: string, role: AccountRoleKey): string => `${accountId}:${role}`

export interface AccountsLoadResult {
    count: number
    results: AccountApi[]
}

const EMPTY_RESULT: AccountsLoadResult = { count: 0, results: [] }

export const accountsLogic = kea<accountsLogicType>([
    path(['scenes', 'customerAnalytics', 'accounts', 'accountsLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            databaseTableListLogic,
            ['allTablesMap', 'databaseLoading'],
            joinsLogic,
            ['joins as warehouseJoins', 'joinsLoading as warehouseJoinsLoading'],
        ],
        actions: [databaseTableListLogic, ['loadDatabase'], joinsLogic, ['loadJoins']],
    })),
    actions({
        setSearchQuery: (query: string) => ({ query }),
        setTagsFilter: (tags: string[]) => ({ tags }),
        setAllRolesUnassigned: (value: boolean) => ({ value }),
        setCsmFilter: (value: RoleFilterValue) => ({ value }),
        setAccountExecutiveFilter: (value: RoleFilterValue) => ({ value }),
        setAccountOwnerFilter: (value: RoleFilterValue) => ({ value }),
        setCurrentPage: (page: number) => ({ page }),
        setActiveView: (view: AccountsView) => ({ view }),
        setSortOrder: (sortOrder: AccountSortOrder) => ({ sortOrder }),
        toggleSort: (column: AccountSortableColumn) => ({ column }),
        setSelectColumns: (columns: string[]) => ({ columns }),
        selectColumn: (column: string) => ({ column }),
        unselectColumn: (column: string) => ({ column }),
        moveColumn: (oldIndex: number, newIndex: number) => ({ oldIndex, newIndex }),
        resetColumns: true,
        saveColumns: true,
        showColumnConfigurator: true,
        hideColumnConfigurator: true,
        refresh: true,
        updateAccountRole: (accountId: string, role: AccountRoleKey, user: UserBasicType | null) => ({
            accountId,
            role,
            user,
        }),
        roleUpdateStarted: (accountId: string, role: AccountRoleKey) => ({ accountId, role }),
        roleUpdateFinished: (accountId: string, role: AccountRoleKey) => ({ accountId, role }),
        replaceAccount: (account: AccountApi) => ({ account }),
        revertAccountOverride: (accountId: string) => ({ accountId }),
    }),
    reducers({
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { query }) => query,
            },
        ],
        tagsFilter: [
            [] as string[],
            {
                setTagsFilter: (_, { tags }) => tags,
            },
        ],
        allRolesUnassigned: [
            false,
            {
                setAllRolesUnassigned: (_, { value }) => value,
            },
        ],
        csmFilter: [
            null as RoleFilterValue,
            {
                setCsmFilter: (_, { value }) => value,
            },
        ],
        accountExecutiveFilter: [
            null as RoleFilterValue,
            {
                setAccountExecutiveFilter: (_, { value }) => value,
            },
        ],
        accountOwnerFilter: [
            null as RoleFilterValue,
            {
                setAccountOwnerFilter: (_, { value }) => value,
            },
        ],
        currentPage: [
            1,
            {
                setCurrentPage: (_, { page }) => page,
            },
        ],
        activeView: [
            'endpoint' as AccountsView,
            {
                setActiveView: (_, { view }) => view,
            },
        ],
        sortOrder: [
            null as AccountSortOrder,
            {
                setSortOrder: (_, { sortOrder }) => sortOrder,
            },
        ],
        selectColumns: [
            [...ACCOUNTS_HOGQL_DEFAULT_SELECT],
            {
                setSelectColumns: (_, { columns }) => columns,
                selectColumn: (state, { column }) =>
                    state.includes(column) ? state : [...state, column],
                unselectColumn: (state, { column }) => state.filter((c) => c !== column),
                moveColumn: (state, { oldIndex, newIndex }) => {
                    if (oldIndex === newIndex || oldIndex < 0 || oldIndex >= state.length) {
                        return state
                    }
                    const next = [...state]
                    const [removed] = next.splice(oldIndex, 1)
                    next.splice(newIndex, 0, removed)
                    return next
                },
                resetColumns: () => [...ACCOUNTS_HOGQL_DEFAULT_SELECT],
                loadSavedColumnConfigurationSuccess: (state, { savedColumnConfiguration }) =>
                    savedColumnConfiguration ? savedColumnConfiguration.columns : state,
            },
        ],
        columnConfiguratorVisible: [
            false,
            {
                showColumnConfigurator: () => true,
                hideColumnConfigurator: () => false,
                saveColumns: () => false,
            },
        ],
        savingRoles: [
            {} as Record<string, true>,
            {
                roleUpdateStarted: (state, { accountId, role }) => ({
                    ...state,
                    [savingRoleKey(accountId, role)]: true,
                }),
                roleUpdateFinished: (state, { accountId, role }) => {
                    const next = { ...state }
                    delete next[savingRoleKey(accountId, role)]
                    return next
                },
            },
        ],
        accountOverrides: [
            {} as Record<string, AccountApi>,
            {
                replaceAccount: (state, { account }) => ({ ...state, [account.id]: account }),
                revertAccountOverride: (state, { accountId }) => {
                    const next = { ...state }
                    delete next[accountId]
                    return next
                },
                loadAccountsSuccess: () => ({}),
            },
        ],
    }),
    loaders(({ values }) => ({
        savedColumnConfiguration: [
            null as { id: string; columns: string[] } | null,
            {
                loadSavedColumnConfiguration: async (): Promise<{ id: string; columns: string[] } | null> => {
                    try {
                        const response = await api.columnConfigurations.list({
                            teamId: values.currentTeamId || undefined,
                            context_key: ACCOUNTS_COLUMN_CONFIG_KEY,
                        })
                        if (response.results && response.results.length > 0) {
                            return {
                                id: response.results[0].id,
                                columns: response.results[0].columns || [],
                            }
                        }
                        return null
                    } catch (error) {
                        posthog.captureException(error as Error, {
                            scope: 'accountsLogic.loadSavedColumnConfiguration',
                        })
                        return null
                    }
                },
            },
        ],
        accounts: [
            EMPTY_RESULT,
            {
                loadAccounts: async (_ = null, breakpoint) => {
                    await breakpoint(300)
                    const projectId = String(values.currentTeamId)
                    const params: Record<string, string | number | boolean> = {
                        limit: ACCOUNTS_PAGE_SIZE,
                        offset: (values.currentPage - 1) * ACCOUNTS_PAGE_SIZE,
                    }
                    if (values.searchQuery.trim()) {
                        params.search = values.searchQuery.trim()
                    }
                    if (values.tagsFilter.length > 0) {
                        params.tags = JSON.stringify(values.tagsFilter)
                    }
                    if (values.allRolesUnassigned) {
                        params.all_roles_unassigned = true
                    }
                    if (values.csmFilter !== null) {
                        params.csm = String(values.csmFilter)
                    }
                    if (values.accountExecutiveFilter !== null) {
                        params.account_executive = String(values.accountExecutiveFilter)
                    }
                    if (values.accountOwnerFilter !== null) {
                        params.account_owner = String(values.accountOwnerFilter)
                    }
                    try {
                        const response = await accountsList(projectId, params)
                        breakpoint()
                        return { count: response.count, results: response.results }
                    } catch (error) {
                        if (!isBreakpoint(error as Error)) {
                            posthog.captureException(error as Error, { scope: 'accountsLogic.loadAccounts' })
                            lemonToast.error('Failed to load accounts')
                        }
                        throw error
                    }
                },
            },
        ],
    })),
    selectors({
        totalCount: [(s) => [s.accounts], (a: AccountsLoadResult): number => a.count],
        results: [
            (s) => [s.accounts, s.accountOverrides],
            (a: AccountsLoadResult, overrides: Record<string, AccountApi>): AccountApi[] =>
                a.results.map((account) => overrides[account.id] ?? account),
        ],
        isRoleSaving: [
            (s) => [s.savingRoles],
            (savingRoles: Record<string, true>) =>
                (accountId: string, role: AccountRoleKey): boolean =>
                    !!savingRoles[savingRoleKey(accountId, role)],
        ],
        visibleColumnNames: [
            (s) => [s.selectColumns],
            (selectColumns: string[]): string[] => selectColumns.map((c) => extractDisplayLabel(c)),
        ],
        accountsColumnGroups: [
            (s) => [s.allTablesMap, s.warehouseJoins],
            (
                allTablesMap: Record<string, DatabaseSchemaTable>,
                warehouseJoins: DataWarehouseViewLink[]
            ): AccountColumnGroup[] => buildAccountColumnGroups(allTablesMap, warehouseJoins),
        ],
        hogqlQuery: [
            (s) => [
                s.searchQuery,
                s.tagsFilter,
                s.allRolesUnassigned,
                s.csmFilter,
                s.accountExecutiveFilter,
                s.accountOwnerFilter,
                s.sortOrder,
                s.selectColumns,
            ],
            (
                searchQuery: string,
                tagsFilter: string[],
                allRolesUnassigned: boolean,
                csmFilter: RoleFilterValue,
                accountExecutiveFilter: RoleFilterValue,
                accountOwnerFilter: RoleFilterValue,
                sortOrder: AccountSortOrder,
                selectColumns: string[]
            ): DataTableNode => {
                const source: AccountsQuery = {
                    kind: NodeKind.AccountsQuery,
                    select: [...ACCOUNTS_HOGQL_PINNED_SELECT, ...selectColumns],
                    tags: { ...CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS, name: 'customer_analytics_accounts_list' },
                }
                const trimmed = searchQuery.trim()
                if (trimmed) {
                    source.search = trimmed
                }
                if (tagsFilter.length > 0) {
                    source.tagNames = tagsFilter
                }
                if (allRolesUnassigned) {
                    source.allRolesUnassigned = true
                }
                if (csmFilter !== null) {
                    source.csm = csmFilter
                }
                if (accountExecutiveFilter !== null) {
                    source.accountExecutive = accountExecutiveFilter
                }
                if (accountOwnerFilter !== null) {
                    source.accountOwner = accountOwnerFilter
                }
                if (sortOrder) {
                    const expr = ACCOUNTS_HOGQL_SORT_EXPRS[sortOrder.column]
                    source.orderBy = [sortOrder.direction === 'asc' ? expr : `${expr} DESC`]
                }
                return {
                    kind: NodeKind.DataTableNode,
                    source,
                    full: true,
                }
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        setSearchQuery: () => {
            actions.setCurrentPage(1)
        },
        setTagsFilter: () => {
            actions.setCurrentPage(1)
        },
        setAllRolesUnassigned: ({ value }) => {
            if (value) {
                if (values.csmFilter !== null) {
                    actions.setCsmFilter(null)
                }
                if (values.accountExecutiveFilter !== null) {
                    actions.setAccountExecutiveFilter(null)
                }
                if (values.accountOwnerFilter !== null) {
                    actions.setAccountOwnerFilter(null)
                }
            }
            actions.setCurrentPage(1)
        },
        setCsmFilter: ({ value }) => {
            if (value !== null && values.allRolesUnassigned) {
                actions.setAllRolesUnassigned(false)
            }
            actions.setCurrentPage(1)
        },
        setAccountExecutiveFilter: ({ value }) => {
            if (value !== null && values.allRolesUnassigned) {
                actions.setAllRolesUnassigned(false)
            }
            actions.setCurrentPage(1)
        },
        setAccountOwnerFilter: ({ value }) => {
            if (value !== null && values.allRolesUnassigned) {
                actions.setAllRolesUnassigned(false)
            }
            actions.setCurrentPage(1)
        },
        setCurrentPage: () => {
            actions.loadAccounts()
        },
        toggleSort: ({ column }) => {
            const current = values.sortOrder
            let next: AccountSortOrder
            if (!current || current.column !== column) {
                next = { column, direction: 'asc' }
            } else if (current.direction === 'asc') {
                next = { column, direction: 'desc' }
            } else {
                next = null
            }
            actions.setSortOrder(next)
        },
        setSortOrder: () => {
            actions.setCurrentPage(1)
        },
        setSelectColumns: () => {
            clearSortIfColumnRemoved(values, actions)
        },
        unselectColumn: () => {
            clearSortIfColumnRemoved(values, actions)
        },
        resetColumns: () => {
            clearSortIfColumnRemoved(values, actions)
        },
        saveColumns: async () => {
            const teamId = values.currentTeamId || undefined
            const columns = values.selectColumns
            try {
                if (values.savedColumnConfiguration?.id) {
                    await api.columnConfigurations.update({
                        teamId,
                        id: values.savedColumnConfiguration.id,
                        data: { columns },
                    })
                } else {
                    const response = await api.columnConfigurations.create({
                        teamId,
                        data: { context_key: ACCOUNTS_COLUMN_CONFIG_KEY, columns },
                    })
                    actions.loadSavedColumnConfigurationSuccess({ id: response.id, columns: response.columns || [] })
                }
                lemonToast.success('Columns saved')
            } catch (error) {
                posthog.captureException(error as Error, { scope: 'accountsLogic.saveColumns' })
                lemonToast.error('Failed to save columns')
            }
        },
        refresh: () => {
            actions.loadAccounts()
            dataNodeLogic.findMounted({ key: ACCOUNTS_HOGQL_DATA_NODE_KEY })?.actions.loadData('force_async')
        },
        updateAccountRole: async ({ accountId, role, user }) => {
            if (values.isRoleSaving(accountId, role)) {
                return
            }
            const account = values.results.find((a) => a.id === accountId)
            if (!account) {
                return
            }
            const previousOverride = values.accountOverrides[accountId]
            const nextProperties: PatchedAccountApiProperties = {
                ...account.properties,
                [role]: user ? { id: user.id, email: user.email } : null,
            }
            const optimisticAccount: AccountApi = { ...account, properties: nextProperties }
            const projectId = String(values.currentTeamId)
            actions.roleUpdateStarted(accountId, role)
            actions.replaceAccount(optimisticAccount)
            try {
                const updated = await accountsPartialUpdate(projectId, accountId, { properties: nextProperties })
                actions.replaceAccount(updated)
                dataNodeLogic.findMounted({ key: ACCOUNTS_HOGQL_DATA_NODE_KEY })?.actions.loadData('force_async')
            } catch (error) {
                if (previousOverride) {
                    actions.replaceAccount(previousOverride)
                } else {
                    actions.revertAccountOverride(accountId)
                }
                posthog.captureException(error as Error, { scope: 'accountsLogic.updateAccountRole' })
                lemonToast.error(`Failed to update ${ROLE_LABELS[role]}`)
            } finally {
                actions.roleUpdateFinished(accountId, role)
            }
        },
    })),
    afterMount(({ actions, values }) => {
        actions.loadAccounts()
        actions.loadSavedColumnConfiguration()
        // Lazily fetch the database schema only if it isn't already in flight / loaded.
        // databaseTableListLogic dedupes concurrent calls internally.
        if (!values.allTablesMap || Object.keys(values.allTablesMap).length === 0) {
            actions.loadDatabase()
        }
    }),
])
