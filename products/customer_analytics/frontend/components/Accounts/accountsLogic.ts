import equal from 'fast-deep-equal'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { AccountsQuery, DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import type { UserBasicType } from '~/types'

import { accountsPartialUpdate, accountsRetrieve } from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountApi,
    PatchedAccountApiProperties,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { ACCOUNTS_HOGQL_DATA_NODE_KEY, CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS } from '../../constants'
import { ACCOUNTS_HOGQL_DEFAULT_SELECT, accountsColumnConfigLogic } from './accountsColumnConfigLogic'
import type { accountsLogicType } from './accountsLogicType'
import { accountsOverviewTilesLogic, TileFilter } from './accountsOverviewTilesLogic'

export const SEARCH_DEBOUNCE_MS = 300

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

export type AccountRoleKey = 'csm' | 'account_executive' | 'account_owner'

// `column` matches the visible column name (alias-stripped) so any selected
// column can drive the sort.
export type AccountSortableColumn = string

export type AccountSortDirection = 'asc' | 'desc'

export type AccountSortOrder = { column: AccountSortableColumn; direction: AccountSortDirection } | null

// Columns that are HogQL `Tuple(id, email)` — sort by the `email` element so the
// order matches what the user sees on screen rather than the opaque user id.
const TUPLE_SORT_COLUMNS = new Set<string>(['csm', 'account_executive', 'account_owner'])

// Resolve the HogQL expression to use in ORDER BY for a sortable column.
// HogQL ORDER BY resolves SELECT aliases by name, so the visible column name
// (which is the alias for aliased entries, or the bare expression otherwise)
// works directly — except for tuple-shaped role columns, where we sort by
// the email element so the visual order matches the rendered cell.
export function deriveAccountsOrderByExpr(column: string): string {
    if (TUPLE_SORT_COLUMNS.has(column)) {
        return `tupleElement(${column}, 2)`
    }
    return column
}

const ROLE_LABELS: Record<AccountRoleKey, string> = {
    csm: 'CSM',
    account_executive: 'Account executive',
    account_owner: 'Account owner',
}

export const savingRoleKey = (accountId: string, role: AccountRoleKey): string => `${accountId}:${role}`

// Shareable view state encoded into the URL hash (`#view=...`) so a copied URL
// reproduces the exact accounts list a colleague is looking at. Only non-default
// values are serialized, keeping the hash empty for the default view.
export interface AccountsViewUrlState {
    search?: string
    tags?: string[]
    unassigned?: boolean
    csm?: number
    accountExecutive?: number
    accountOwner?: number
    sort?: NonNullable<AccountSortOrder>
    columns?: string[]
    tileFilter?: TileFilter
}

export const accountsLogic = kea<accountsLogicType>([
    path(['scenes', 'customerAnalytics', 'accounts', 'accountsLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            accountsColumnConfigLogic,
            ['selectColumns', 'visibleColumnNames'],
            accountsOverviewTilesLogic,
            ['metrics as overviewMetrics', 'tileFilter'],
        ],
        actions: [
            accountsColumnConfigLogic,
            [
                'setSelectColumns',
                'selectColumn',
                'unselectColumn',
                'moveColumn',
                'resetColumns',
                'markColumnsOverriddenByUrl',
            ],
            accountsOverviewTilesLogic,
            ['setTileFilter'],
        ],
    })),
    actions({
        setSearchInput: (query: string) => ({ query }),
        setSearchQuery: (query: string) => ({ query }),
        setTagsFilter: (tags: string[]) => ({ tags }),
        setAllRolesUnassigned: (value: boolean) => ({ value }),
        setCsmFilter: (value: RoleFilterValue) => ({ value }),
        setAccountExecutiveFilter: (value: RoleFilterValue) => ({ value }),
        setAccountOwnerFilter: (value: RoleFilterValue) => ({ value }),
        setSortOrder: (sortOrder: AccountSortOrder) => ({ sortOrder }),
        toggleSort: (column: AccountSortableColumn) => ({ column }),
        refresh: true,
        updateAccountRole: (accountId: string, role: AccountRoleKey, user: UserBasicType | null) => ({
            accountId,
            role,
            user,
        }),
        roleUpdateStarted: (accountId: string, role: AccountRoleKey) => ({ accountId, role }),
        roleUpdateFinished: (accountId: string, role: AccountRoleKey) => ({ accountId, role }),
        replaceAccount: (account: AccountApi) => ({ account }),
    }),
    reducers({
        searchInput: [
            '',
            {
                setSearchInput: (_, { query }) => query,
                setSearchQuery: (_, { query }) => query,
            },
        ],
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
        sortOrder: [
            null as AccountSortOrder,
            {
                setSortOrder: (_, { sortOrder }) => sortOrder,
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
            },
        ],
    }),
    selectors({
        isRoleSaving: [
            (s) => [s.savingRoles],
            (savingRoles: Record<string, true>) =>
                (accountId: string, role: AccountRoleKey): boolean =>
                    !!savingRoles[savingRoleKey(accountId, role)],
        ],
        viewUrlState: [
            (s) => [
                s.searchQuery,
                s.tagsFilter,
                s.allRolesUnassigned,
                s.csmFilter,
                s.accountExecutiveFilter,
                s.accountOwnerFilter,
                s.sortOrder,
                s.selectColumns,
                s.tileFilter,
            ],
            (
                searchQuery: string,
                tagsFilter: string[],
                allRolesUnassigned: boolean,
                csmFilter: RoleFilterValue,
                accountExecutiveFilter: RoleFilterValue,
                accountOwnerFilter: RoleFilterValue,
                sortOrder: AccountSortOrder,
                selectColumns: string[],
                tileFilter: TileFilter | null
            ): AccountsViewUrlState => {
                const state: AccountsViewUrlState = {}
                const trimmedSearch = searchQuery.trim()
                if (trimmedSearch) {
                    state.search = trimmedSearch
                }
                if (tagsFilter.length > 0) {
                    state.tags = tagsFilter
                }
                if (allRolesUnassigned) {
                    state.unassigned = true
                }
                if (csmFilter !== null) {
                    state.csm = csmFilter
                }
                if (accountExecutiveFilter !== null) {
                    state.accountExecutive = accountExecutiveFilter
                }
                if (accountOwnerFilter !== null) {
                    state.accountOwner = accountOwnerFilter
                }
                if (sortOrder) {
                    state.sort = sortOrder
                }
                if (!equal(selectColumns, ACCOUNTS_HOGQL_DEFAULT_SELECT)) {
                    state.columns = selectColumns
                }
                if (tileFilter) {
                    state.tileFilter = tileFilter
                }
                return state
            },
        ],
        hogqlQuery: [
            (s) => [
                s.searchQuery,
                s.tagsFilter,
                s.allRolesUnassigned,
                s.csmFilter,
                s.accountExecutiveFilter,
                s.accountOwnerFilter,
                s.tileFilter,
                s.overviewMetrics,
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
                tileFilter: TileFilter | null,
                overviewMetrics: string[],
                sortOrder: AccountSortOrder,
                selectColumns: string[]
            ): DataTableNode => {
                const source: AccountsQuery = {
                    kind: NodeKind.AccountsQuery,
                    select: selectColumns,
                    tags: { ...CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS, name: 'customer_analytics_accounts_list' },
                }
                if (overviewMetrics.length > 0) {
                    source.metrics = overviewMetrics
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
                if (tileFilter) {
                    source.filterExpression = tileFilter.expression
                }
                if (sortOrder) {
                    const expr = deriveAccountsOrderByExpr(sortOrder.column)
                    source.orderBy = [sortOrder.direction === 'asc' ? expr : `${expr} DESC`]
                }
                return {
                    kind: NodeKind.DataTableNode,
                    source,
                    full: true,
                    // Suppress DataTable's built-in sort indicator on column
                    // headers — our `SortableColumnHeader` renders its own (and
                    // correctly reflects sorts where the orderBy expression
                    // differs from the column name, e.g. `tupleElement(csm, 2)`).
                    allowSorting: true,
                }
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        setSearchInput: async ({ query }, breakpoint) => {
            await breakpoint(SEARCH_DEBOUNCE_MS)
            actions.setSearchQuery(query)
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
        },
        setCsmFilter: ({ value }) => {
            if (value !== null && values.allRolesUnassigned) {
                actions.setAllRolesUnassigned(false)
            }
        },
        setAccountExecutiveFilter: ({ value }) => {
            if (value !== null && values.allRolesUnassigned) {
                actions.setAllRolesUnassigned(false)
            }
        },
        setAccountOwnerFilter: ({ value }) => {
            if (value !== null && values.allRolesUnassigned) {
                actions.setAllRolesUnassigned(false)
            }
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
        setSelectColumns: () => {
            clearSortIfColumnRemoved(values, actions)
        },
        unselectColumn: () => {
            clearSortIfColumnRemoved(values, actions)
        },
        resetColumns: () => {
            clearSortIfColumnRemoved(values, actions)
        },
        refresh: () => {
            dataNodeLogic.findMounted({ key: ACCOUNTS_HOGQL_DATA_NODE_KEY })?.actions.loadData('force_async')
        },
        updateAccountRole: async ({ accountId, role, user }) => {
            if (values.isRoleSaving(accountId, role)) {
                return
            }
            const projectId = String(values.currentTeamId)
            actions.roleUpdateStarted(accountId, role)
            try {
                const current = await accountsRetrieve(projectId, accountId)
                const nextProperties: PatchedAccountApiProperties = {
                    ...current.properties,
                    [role]: user ? { id: user.id, email: user.email } : null,
                }
                const updated = await accountsPartialUpdate(projectId, accountId, { properties: nextProperties })
                actions.replaceAccount(updated)
                dataNodeLogic.findMounted({ key: ACCOUNTS_HOGQL_DATA_NODE_KEY })?.actions.loadData('force_async')
            } catch (error) {
                posthog.captureException(error as Error, { scope: 'accountsLogic.updateAccountRole' })
                lemonToast.error(`Failed to update ${ROLE_LABELS[role]}`)
            } finally {
                actions.roleUpdateFinished(accountId, role)
            }
        },
    })),
    actionToUrl(({ values }) => {
        // Mirror the full view into the URL hash so the link is shareable.
        // Search params are preserved untouched — the parent scene owns those.
        const toUrl = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] => [
            urls.customerAnalyticsAccounts(),
            router.values.searchParams,
            equal(values.viewUrlState, {}) ? {} : { view: values.viewUrlState },
            { replace: true },
        ]
        return {
            setSearchQuery: toUrl,
            setTagsFilter: toUrl,
            setAllRolesUnassigned: toUrl,
            setCsmFilter: toUrl,
            setAccountExecutiveFilter: toUrl,
            setAccountOwnerFilter: toUrl,
            setSortOrder: toUrl,
            setSelectColumns: toUrl,
            selectColumn: toUrl,
            unselectColumn: toUrl,
            moveColumn: toUrl,
            resetColumns: toUrl,
            setTileFilter: toUrl,
        }
    }),
    urlToAction(({ actions, values }) => ({
        [urls.customerAnalyticsAccounts()]: (_, __, hashParams): void => {
            const view: AccountsViewUrlState =
                hashParams?.view && typeof hashParams.view === 'object' ? hashParams.view : {}

            const search = view.search ?? ''
            if (search !== values.searchQuery) {
                actions.setSearchQuery(search)
            }

            const tags = view.tags ?? []
            if (!equal(tags, values.tagsFilter)) {
                actions.setTagsFilter(tags)
            }

            const unassigned = view.unassigned ?? false
            if (unassigned !== values.allRolesUnassigned) {
                actions.setAllRolesUnassigned(unassigned)
            }

            const csm = view.csm ?? null
            if (csm !== values.csmFilter) {
                actions.setCsmFilter(csm)
            }

            const accountExecutive = view.accountExecutive ?? null
            if (accountExecutive !== values.accountExecutiveFilter) {
                actions.setAccountExecutiveFilter(accountExecutive)
            }

            const accountOwner = view.accountOwner ?? null
            if (accountOwner !== values.accountOwnerFilter) {
                actions.setAccountOwnerFilter(accountOwner)
            }

            const sort = view.sort ?? null
            if (!equal(sort, values.sortOrder)) {
                actions.setSortOrder(sort)
            }

            // A shared link's columns must win over the per-user saved column
            // config, which loads asynchronously after mount — the guard makes
            // the late-arriving saved config defer to the URL.
            if (view.columns) {
                if (!equal(view.columns, values.selectColumns)) {
                    actions.setSelectColumns(view.columns)
                }
                actions.markColumnsOverriddenByUrl()
            }

            const tileFilter = view.tileFilter ?? null
            if (!equal(tileFilter, values.tileFilter)) {
                actions.setTileFilter(tileFilter)
            }
        },
    })),
])
