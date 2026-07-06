import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { isUUIDLike } from 'lib/utils/guards'
import { objectsEqual } from 'lib/utils/objects'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { AccountsQuery, DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import type { UserBasicType } from '~/types'

import { accountsPartialUpdate, accountsRetrieve } from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountApi,
    PatchedAccountApiProperties,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import {
    ACCOUNTS_HOGQL_DATA_NODE_KEY,
    ACCOUNTS_METRICS_DATA_NODE_KEY,
    CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS,
} from '../../constants'
import {
    ACCOUNTS_HOGQL_DEFAULT_SELECT,
    ACCOUNTS_NAME_COLUMN,
    accountsColumnConfigLogic,
} from './accountsColumnConfigLogic'
import {
    ACCOUNT_EXPANSION_TABS,
    AccountExpansionTab,
    accountsExpansionLogic,
    DEFAULT_ACCOUNT_TAB,
} from './accountsExpansionLogic'
import type { accountsLogicType } from './accountsLogicType'
import { accountsOverviewTilesLogic, TileFilter } from './accountsOverviewTilesLogic'
import { normalizeRoleFilter } from './accountsViewState'
import { AccountsEvents } from './constants'

export const SEARCH_DEBOUNCE_MS = 300

// Revealing an off-screen account triggers an async refetch, so its row may not
// be in the DOM yet — poll briefly for it before scrolling.
const SCROLL_TO_ACCOUNT_POLL_MS = 100
const SCROLL_TO_ACCOUNT_MAX_ATTEMPTS = 40

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

export type RoleFilterValue = number[]

export type AccountRoleKey = 'csm' | 'account_executive' | 'account_owner'

export type AccountFilterType = 'tag' | 'unassigned_only' | 'my_accounts' | 'assigned_to'

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

interface AccountQueryFilters {
    searchQuery: string
    tagsFilter: string[]
    allRolesUnassigned: boolean
    assignedToFilter: RoleFilterValue
    accountIdFilter: string | null
    tileFilter: TileFilter | null
}

// Shared filter clauses for the list-rows query and the overview-metrics query,
// so both always aggregate/list over the exact same set of accounts.
function applyAccountFilters(source: AccountsQuery, filters: AccountQueryFilters): void {
    const trimmed = filters.searchQuery.trim()
    if (trimmed) {
        source.search = trimmed
    }
    if (filters.tagsFilter.length > 0) {
        source.tagNames = filters.tagsFilter
    }
    if (filters.allRolesUnassigned) {
        source.allRolesUnassigned = true
    }
    if (filters.assignedToFilter.length > 0) {
        source.assignedToUserIds = filters.assignedToFilter
    }
    // Combine the overview-tile filter with the single-account filter (path route). The
    // id is the account PK; compare it stringified, matching how the name-cell id is built.
    // accountIdFilter is only ever a validated UUID (set from the route), so it's injection-safe.
    const filterExpressions: string[] = []
    if (filters.tileFilter) {
        filterExpressions.push(filters.tileFilter.expression)
    }
    if (filters.accountIdFilter) {
        filterExpressions.push(`toString(id) = '${filters.accountIdFilter}'`)
    }
    if (filterExpressions.length > 0) {
        source.filterExpression = filterExpressions.map((expr) => `(${expr})`).join(' AND ')
    }
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
    /** Concrete user ids for the "Assigned to" / "My accounts" filter — explicit
     * (not viewer-relative) so a shared link resolves identically for everyone. */
    assignedTo?: number[]
    /** @deprecated Legacy viewer-relative flag; still read so old shared links
     * resolve to the opener's own id. Never written. */
    mine?: boolean
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
            userLogic,
            ['user'],
            accountsColumnConfigLogic,
            ['selectColumns', 'visibleColumnNames'],
            accountsOverviewTilesLogic,
            ['metrics as overviewMetrics', 'tileFilter'],
        ],
        actions: [
            accountsColumnConfigLogic,
            ['setSelectColumns', 'selectColumn', 'unselectColumn', 'moveColumn', 'resetColumns'],
            accountsOverviewTilesLogic,
            ['setTileFilter'],
            accountsExpansionLogic,
            ['openAccountTab'],
        ],
    })),
    actions({
        setSearchInput: (query: string) => ({ query }),
        setSearchQuery: (query: string) => ({ query }),
        setTagsFilter: (tags: string[]) => ({ tags }),
        setAllRolesUnassigned: (value: boolean) => ({ value }),
        setAssignedToFilter: (value: RoleFilterValue) => ({ value }),
        // Shortcut for the "My accounts" checkbox — resolves to the current
        // user's id and routes through setAssignedToFilter.
        setAssignedToCurrentUser: (value: boolean) => ({ value }),
        setSortOrder: (sortOrder: AccountSortOrder) => ({ sortOrder }),
        toggleSort: (column: AccountSortableColumn) => ({ column }),
        refresh: true,
        // Dispatched by the filter controls on genuine user interaction only.
        // The raw filter setters are also fired by URL sync and cross-filter
        // cascades, so capturing analytics here keeps phantom events out.
        reportFilterChange: (filterType: AccountFilterType) => ({ filterType }),
        updateAccountRole: (accountId: string, role: AccountRoleKey, user: UserBasicType | null) => ({
            accountId,
            role,
            user,
        }),
        roleUpdateStarted: (accountId: string, role: AccountRoleKey) => ({ accountId, role }),
        roleUpdateFinished: (accountId: string, role: AccountRoleKey) => ({ accountId, role }),
        replaceAccount: (account: AccountApi) => ({ account }),
        openAccount: (accountId: string, externalId: string | null, name: string, tab: AccountExpansionTab) => ({
            accountId,
            externalId,
            name,
            tab,
        }),
        // Restrict the list to a single account by id — drives the `/accounts/:accountId/:tab`
        // path route. null clears it (back to the full list).
        setAccountIdFilter: (accountId: string | null) => ({ accountId }),
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
        assignedToFilter: [
            [] as RoleFilterValue,
            {
                setAssignedToFilter: (_, { value }) => value,
            },
        ],
        accountIdFilter: [
            null as string | null,
            {
                setAccountIdFilter: (_, { accountId }) => accountId,
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
        currentUserId: [(s) => [s.user], (user): number | null => user?.id ?? null],
        // The "My accounts" checkbox is checked exactly when the assigned-to
        // filter is just the current user — i.e. the user-agnostic id filter
        // happens to point at you.
        assignedToCurrentUser: [
            (s) => [s.assignedToFilter, s.currentUserId],
            (assignedToFilter: RoleFilterValue, currentUserId: number | null): boolean =>
                currentUserId !== null && assignedToFilter.length === 1 && assignedToFilter[0] === currentUserId,
        ],
        isRoleSaving: [
            (s) => [s.savingRoles],
            (savingRoles: Record<string, true>) =>
                (accountId: string, role: AccountRoleKey): boolean =>
                    !!savingRoles[savingRoleKey(accountId, role)],
        ],
        activeFilterCount: [
            (s) => [s.searchQuery, s.tagsFilter, s.allRolesUnassigned, s.assignedToFilter],
            (
                searchQuery: string,
                tagsFilter: string[],
                allRolesUnassigned: boolean,
                assignedToFilter: RoleFilterValue
            ): number =>
                [!!searchQuery.trim(), tagsFilter.length > 0, allRolesUnassigned, assignedToFilter.length > 0].filter(
                    Boolean
                ).length,
        ],
        viewUrlState: [
            (s) => [
                s.searchQuery,
                s.tagsFilter,
                s.allRolesUnassigned,
                s.assignedToFilter,
                s.sortOrder,
                s.selectColumns,
                s.tileFilter,
            ],
            (
                searchQuery: string,
                tagsFilter: string[],
                allRolesUnassigned: boolean,
                assignedToFilter: RoleFilterValue,
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
                if (assignedToFilter.length > 0) {
                    state.assignedTo = assignedToFilter
                }
                if (sortOrder) {
                    state.sort = sortOrder
                }
                if (!objectsEqual(selectColumns, ACCOUNTS_HOGQL_DEFAULT_SELECT)) {
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
                s.assignedToFilter,
                s.accountIdFilter,
                s.tileFilter,
                s.sortOrder,
                s.selectColumns,
            ],
            (
                searchQuery: string,
                tagsFilter: string[],
                allRolesUnassigned: boolean,
                assignedToFilter: RoleFilterValue,
                accountIdFilter: string | null,
                tileFilter: TileFilter | null,
                sortOrder: AccountSortOrder,
                selectColumns: string[]
            ): DataTableNode => {
                const source: AccountsQuery = {
                    kind: NodeKind.AccountsQuery,
                    select: selectColumns,
                    tags: { ...CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS, name: 'customer_analytics_accounts_list' },
                }
                applyAccountFilters(source, {
                    searchQuery,
                    tagsFilter,
                    allRolesUnassigned,
                    assignedToFilter,
                    accountIdFilter,
                    tileFilter,
                })
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
        // The overview-tile aggregations run as their own metrics-only query (no
        // `select`), keyed to ACCOUNTS_METRICS_DATA_NODE_KEY, so they load
        // independently of the list rows. Null when there are no tiles — the
        // data node then stays idle. Shares the list's filters so tiles
        // aggregate over the same set the table shows.
        metricsQuery: [
            (s) => [
                s.overviewMetrics,
                s.searchQuery,
                s.tagsFilter,
                s.allRolesUnassigned,
                s.assignedToFilter,
                s.accountIdFilter,
                s.tileFilter,
            ],
            (
                overviewMetrics: string[],
                searchQuery: string,
                tagsFilter: string[],
                allRolesUnassigned: boolean,
                assignedToFilter: RoleFilterValue,
                accountIdFilter: string | null,
                tileFilter: TileFilter | null
            ): AccountsQuery | null => {
                if (overviewMetrics.length === 0) {
                    return null
                }
                const source: AccountsQuery = {
                    kind: NodeKind.AccountsQuery,
                    metrics: overviewMetrics,
                    tags: { ...CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS, name: 'customer_analytics_accounts_overview' },
                }
                applyAccountFilters(source, {
                    searchQuery,
                    tagsFilter,
                    allRolesUnassigned,
                    assignedToFilter,
                    accountIdFilter,
                    tileFilter,
                })
                return source
            },
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        setSearchInput: async ({ query }, breakpoint) => {
            await breakpoint(SEARCH_DEBOUNCE_MS)
            actions.setSearchQuery(query)
            const trimmed = query.trim()
            posthog.capture(AccountsEvents.Searched, {
                query_length: trimmed.length,
                has_query: !!trimmed,
                active_filter_count: values.activeFilterCount,
            })
        },
        reportFilterChange: ({ filterType }) => {
            const properties: Record<string, unknown> = {
                filter_type: filterType,
                active_filter_count: values.activeFilterCount,
            }
            switch (filterType) {
                case 'tag':
                    properties.value = values.tagsFilter
                    properties.tag_count = values.tagsFilter.length
                    properties.is_cleared = values.tagsFilter.length === 0
                    break
                case 'unassigned_only':
                    properties.value = values.allRolesUnassigned
                    properties.is_cleared = !values.allRolesUnassigned
                    break
                case 'my_accounts':
                    properties.value = values.assignedToCurrentUser
                    properties.is_cleared = !values.assignedToCurrentUser
                    break
                case 'assigned_to':
                    properties.value = values.assignedToFilter
                    properties.role_count = values.assignedToFilter.length
                    properties.is_cleared = values.assignedToFilter.length === 0
                    break
            }
            posthog.capture(AccountsEvents.FilterChanged, properties)
        },
        setAllRolesUnassigned: ({ value }) => {
            if (value && values.assignedToFilter.length > 0) {
                actions.setAssignedToFilter([])
            }
        },
        // "My accounts" is a shortcut: filter by the current user's own id. The
        // user-agnostic id then rides in the URL, so a shared link shows the
        // sharer's accounts to whoever opens it (not the opener's own).
        setAssignedToCurrentUser: ({ value }) => {
            actions.setAssignedToFilter(value && values.currentUserId !== null ? [values.currentUserId] : [])
        },
        // "Assigned to" (an account's CSM or AE is one of these users) clears the
        // unassigned flag — the two are a genuine contradiction.
        setAssignedToFilter: ({ value }) => {
            if (value.length > 0 && values.allRolesUnassigned) {
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
            posthog.capture(AccountsEvents.Sorted, {
                column,
                direction: next ? next.direction : 'cleared',
            })
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
            posthog.capture(AccountsEvents.Refreshed, {
                has_search: !!values.searchQuery.trim(),
                active_filter_count: values.activeFilterCount,
                sort_column: values.sortOrder?.column ?? null,
            })
            dataNodeLogic.findMounted({ key: ACCOUNTS_HOGQL_DATA_NODE_KEY })?.actions.loadData('force_async')
            dataNodeLogic.findMounted({ key: ACCOUNTS_METRICS_DATA_NODE_KEY })?.actions.loadData('force_async')
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
                posthog.capture(AccountsEvents.RoleAssigned, {
                    role,
                    is_assigned: user !== null,
                    assigned_user_id: user?.id ?? null,
                    source: 'list_row',
                })
                dataNodeLogic.findMounted({ key: ACCOUNTS_HOGQL_DATA_NODE_KEY })?.actions.loadData('force_async')
                dataNodeLogic.findMounted({ key: ACCOUNTS_METRICS_DATA_NODE_KEY })?.actions.loadData('force_async')
            } catch (error) {
                posthog.captureException(error as Error, { scope: 'accountsLogic.updateAccountRole' })
                lemonToast.error(`Failed to update ${ROLE_LABELS[role]}`)
            } finally {
                actions.roleUpdateFinished(accountId, role)
            }
        },
        openAccount: ({ accountId, externalId, name, tab }) => {
            const dataNode = dataNodeLogic.findMounted({ key: ACCOUNTS_HOGQL_DATA_NODE_KEY })
            const results = (dataNode?.values.response as { results?: unknown[] } | undefined)?.results
            const rows = Array.isArray(results) ? results : []
            const nameIndex = values.visibleColumnNames.indexOf(ACCOUNTS_NAME_COLUMN)
            const isVisible =
                nameIndex >= 0 &&
                rows.some((row) => {
                    const cell = Array.isArray(row) ? (row as unknown[])[nameIndex] : undefined
                    return !!cell && typeof cell === 'object' && (cell as { id?: string }).id === accountId
                })
            // Reveal the account if it isn't currently shown, so the expanded row actually renders.
            if (!isVisible) {
                if (values.tagsFilter.length > 0) {
                    actions.setTagsFilter([])
                }
                if (values.allRolesUnassigned) {
                    actions.setAllRolesUnassigned(false)
                }
                if (values.assignedToFilter.length > 0) {
                    actions.setAssignedToFilter([])
                }
                const term = externalId || name
                if (term) {
                    actions.setSearchQuery(term)
                }
            }
            actions.openAccountTab(accountId, tab)
            // Keyed so a second open cancels a still-pending scroll. One-shot, so
            // it opts out of pause-on-hidden rather than re-scrolling on tab return.
            cache.disposables.add(
                () => {
                    let attempts = 0
                    let timer: number | undefined
                    const scrollWhenReady = (): void => {
                        const row = document.querySelector(`[data-account-id="${accountId}"]`)
                        if (row) {
                            row.scrollIntoView({ behavior: 'smooth', block: 'center' })
                            return
                        }
                        attempts += 1
                        if (attempts < SCROLL_TO_ACCOUNT_MAX_ATTEMPTS) {
                            timer = window.setTimeout(scrollWhenReady, SCROLL_TO_ACCOUNT_POLL_MS)
                        }
                    }
                    scrollWhenReady()
                    return () => window.clearTimeout(timer)
                },
                'scrollToAccount',
                { pauseOnPageHidden: false }
            )
        },
    })),
    afterMount(() => {
        posthog.capture(AccountsEvents.ListViewed)
    }),
    actionToUrl(({ values }) => {
        // Mirror the full view into the URL hash so the link is shareable.
        // Search params are preserved untouched — the parent scene owns those.
        const toUrl = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] => [
            urls.customerAnalyticsAccounts(),
            router.values.searchParams,
            objectsEqual(values.viewUrlState, {}) ? {} : { view: values.viewUrlState },
            { replace: true },
        ]
        return {
            setSearchQuery: toUrl,
            setTagsFilter: toUrl,
            setAllRolesUnassigned: toUrl,
            setAssignedToFilter: toUrl,
            setSortOrder: toUrl,
            setSelectColumns: toUrl,
            selectColumn: toUrl,
            unselectColumn: toUrl,
            moveColumn: toUrl,
            resetColumns: toUrl,
            setTileFilter: toUrl,
        }
    }),
    urlToAction(({ actions, values }) => {
        // Path route `/accounts/:accountId/:tab`: filter the list to one account and open the tab.
        // Neither setter is wired into actionToUrl, so the URL stays on the path (no navigate-away).
        const openAccountByPath = (accountId: string | undefined, rawTab?: string): void => {
            // Guard the path param before it's interpolated into the HogQL id filter.
            if (!accountId || !isUUIDLike(accountId)) {
                return
            }
            const tab =
                rawTab && ACCOUNT_EXPANSION_TABS.includes(rawTab as AccountExpansionTab)
                    ? (rawTab as AccountExpansionTab)
                    : DEFAULT_ACCOUNT_TAB
            if (values.accountIdFilter !== accountId) {
                actions.setAccountIdFilter(accountId)
            }
            actions.openAccountTab(accountId, tab)
        }
        return {
            [urls.customerAnalyticsAccounts()]: (_, __, hashParams): void => {
                const view: AccountsViewUrlState =
                    hashParams?.view && typeof hashParams.view === 'object' ? hashParams.view : {}

                const search = view.search ?? ''
                if (search !== values.searchQuery) {
                    actions.setSearchQuery(search)
                }

                const tags = view.tags ?? []
                if (!objectsEqual(tags, values.tagsFilter)) {
                    actions.setTagsFilter(tags)
                }

                const unassigned = view.unassigned ?? false
                if (unassigned !== values.allRolesUnassigned) {
                    actions.setAllRolesUnassigned(unassigned)
                }

                const assignedTo = normalizeRoleFilter(view.assignedTo)
                // Back-compat: legacy links encoded the viewer-relative `mine: true`;
                // resolve it to the opener's own id so old shared links still work.
                const legacyMine =
                    !assignedTo.length && view.mine && values.currentUserId !== null ? [values.currentUserId] : []
                const nextAssignedTo = assignedTo.length ? assignedTo : legacyMine
                if (!objectsEqual(nextAssignedTo, values.assignedToFilter)) {
                    actions.setAssignedToFilter(nextAssignedTo)
                }

                const sort = view.sort ?? null
                if (!objectsEqual(sort, values.sortOrder)) {
                    actions.setSortOrder(sort)
                }

                // A shared link's columns win over the per-user saved column config;
                // accountsColumnConfigLogic enforces this by reading the URL when its
                // async saved-config load resolves.
                if (view.columns && !objectsEqual(view.columns, values.selectColumns)) {
                    actions.setSelectColumns(view.columns)
                }

                const tileFilter = view.tileFilter ?? null
                if (!objectsEqual(tileFilter, values.tileFilter)) {
                    actions.setTileFilter(tileFilter)
                }

                // Back on the bare list — drop any single-account path filter.
                if (values.accountIdFilter !== null) {
                    actions.setAccountIdFilter(null)
                }
            },
            [urls.customerAnalyticsAccount(':accountId')]: ({ accountId }): void => openAccountByPath(accountId),
            [urls.customerAnalyticsAccount(':accountId', ':tab')]: ({ accountId, tab }): void =>
                openAccountByPath(accountId, tab),
        }
    }),
])
