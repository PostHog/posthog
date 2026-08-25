import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { isUUIDLike } from 'lib/utils/guards'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { objectsEqual } from 'lib/utils/objects'
import { membersLogic } from 'scenes/organization/membersLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { tagsModel } from '~/models/tagsModel'
import { type DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { DataTableRow } from '~/queries/nodes/DataTable/dataTableLogic'
import {
    AccountsTableMetric,
    AccountsTableQuery,
    DataNode,
    DataTableNode,
    NodeKind,
    RefreshType,
} from '~/queries/schema/schema-general'
import type { UserBasicType } from '~/types'

import {
    accountsPartialUpdate,
    accountsRelationshipsCreate,
    accountsRelationshipsEndCreate,
    accountsRelationshipsList,
} from 'products/customer_analytics/frontend/generated/api'

import type { UserType } from '../../../../../frontend/src/types'
import {
    ACCOUNTS_TABLE_DATA_NODE_KEY,
    ACCOUNTS_METRICS_DATA_NODE_KEY,
    CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS,
} from '../../constants'
import { customerAnalyticsSceneLogic } from '../../customerAnalyticsSceneLogic'
import type { AccountRelationshipDefinitionApi, CustomPropertyDefinitionApi } from '../../generated/api.schemas'
import { accountsColumnConfigLogic, isLegacyRoleColumn } from './accountsColumnConfigLogic'
import type { AccountColumnDisplayState } from './accountsColumnConfigLogic'
import {
    ACCOUNT_EXPANSION_TABS,
    AccountExpansionTab,
    accountsExpansionLogic,
    DEFAULT_ACCOUNT_TAB,
} from './accountsExpansionLogic'
import { accountsOverviewTilesLogic, TileFilter } from './accountsOverviewTilesLogic'
import type { AccountFilter } from './accountsPropertyFilters'
import { sortAccountRows } from './accountsSort'
import {
    AccountsTableQueryPlan,
    BuildAccountsTableQueryPlanInput,
    accountsTableCell,
    buildAccountsTableQueryPlan,
    isAccountsTableRow,
    supportedAccountFilters,
} from './accountsTableQuery'
import { normalizeRoleFilter } from './accountsViewState'
import { AccountsEvents } from './constants'

export const SEARCH_DEBOUNCE_MS = 300

// ObjectTags fires onChange per added/removed tag; the debounce collapses an
// editing burst into one full-list PATCH.
export const TAGS_SAVE_DEBOUNCE_MS = 300

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

export type AccountFilterType = 'tag' | 'unassigned_only' | 'my_accounts' | 'assigned_to'

// `column` matches the visible column name (alias-stripped) so any selected
// column can drive the sort.
export type AccountSortableColumn = string

export type AccountSortDirection = 'asc' | 'desc'

export type AccountSortOrder = { column: AccountSortableColumn; direction: AccountSortDirection } | null

export const savingRoleKey = (accountId: string, column: string): string => `${accountId}:${column}`

// Which accounts path the shareable view state gets written back to. It must be the path we are
// already on: the setters that mirror view state into the URL also fire while state is being
// restored (the default-column upgrade once relationship definitions load, the auto-restored saved
// view), so pointing them at the list would bounce a single-account deep link to the unfiltered
// list moments after it opened. Returns the live pathname so the deep link keeps its `/:tab`.
function accountsPathToWriteBackTo(accountIdFilter: string | null): string {
    const pathname = removeProjectIdIfPresent(router.values.location.pathname)
    const deepLinkPath = accountIdFilter ? urls.customerAnalyticsAccount(accountIdFilter) : null
    return deepLinkPath && pathname.startsWith(deepLinkPath) ? pathname : urls.customerAnalyticsAccounts()
}

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
    columnDisplay?: AccountColumnDisplayState
    tileFilter?: TileFilter
    customProperties?: AccountFilter[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface accountsLogicValues {
    aliasToDefinition: Record<string, CustomPropertyDefinitionApi> // accountsColumnConfigLogic
    aliasToRelationshipDefinition: Record<string, AccountRelationshipDefinitionApi> // accountsColumnConfigLogic
    columnDisplay: AccountColumnDisplayState // accountsColumnConfigLogic
    customPropertyDefinitionsById: Record<string, CustomPropertyDefinitionApi> // accountsColumnConfigLogic
    defaultSelectColumns: string[] // accountsColumnConfigLogic
    querySelectColumns: string[] // accountsColumnConfigLogic
    relationshipDefinitionsLoaded: boolean // accountsColumnConfigLogic
    selectColumns: string[] // accountsColumnConfigLogic
    visibleColumnNames: string[] // accountsColumnConfigLogic
    overviewMetrics: AccountsTableMetric[] // accountsOverviewTilesLogic
    tileFilter: TileFilter | null // accountsOverviewTilesLogic
    mineOnly: boolean // customerAnalyticsSceneLogic
    listHasMoreData: boolean // dataNodeLogic
    currentTeamId: number | null // teamLogic
    user: UserType | null // userLogic
    accountFilters: AccountFilter[]
    accountIdFilter: string | null
    accountsDataTableQuery: DataTableNode
    accountsQuerySource: AccountsTableQuery | null
    accountsTableQueryPlan: AccountsTableQueryPlan
    accountsTableQueryPlanInput: BuildAccountsTableQueryPlanInput
    activeFilterCount: number
    allRolesUnassigned: boolean
    assignedToCurrentUser: boolean
    assignedToFilter: RoleFilterValue
    canSortClientSide: boolean
    currentUserId: number | null
    isRoleSaving: (accountId: string, column: string) => boolean
    isTagsSaving: (accountId: string) => boolean
    listPaginated: boolean
    metricsQuery: AccountsTableQuery | null
    relationshipOverrides: Record<string, number[]>
    savingRoles: Record<string, true>
    savingTags: Record<string, true>
    searchInput: string
    searchQuery: string
    sortOrder: AccountSortOrder
    sortedRowsTransformer: ((rows: DataTableRow[]) => DataTableRow[]) | undefined
    tagOverrides: Record<string, string[]>
    tagsFilter: string[]
    viewUrlState: AccountsViewUrlState
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface accountsLogicActions {
    loadCustomPropertyDefinitionsSuccess: (
        customPropertyDefinitions: CustomPropertyDefinitionApi[],
        payload?: any
    ) => {
        customPropertyDefinitions: CustomPropertyDefinitionApi[]
        payload?: any
    } // accountsColumnConfigLogic
    moveColumn: (
        oldIndex: number,
        newIndex: number
    ) => {
        newIndex: number
        oldIndex: number
    } // accountsColumnConfigLogic
    resetColumns: () => {
        value: true
    } // accountsColumnConfigLogic
    selectColumn: (column: string) => {
        column: string
    } // accountsColumnConfigLogic
    setColumnDisplay: (
        definitionId: string,
        config: null | import('./accountsColumnConfigLogic').AccountColumnDisplayConfig
    ) => {
        config: null | import('./accountsColumnConfigLogic').AccountColumnDisplayConfig
        definitionId: string
    } // accountsColumnConfigLogic
    setColumnDisplayConfig: (config: AccountColumnDisplayState) => {
        config: AccountColumnDisplayState
    } // accountsColumnConfigLogic
    setSelectColumns: (columns: string[]) => {
        columns: string[]
    } // accountsColumnConfigLogic
    unselectColumn: (column: string) => {
        column: string
    } // accountsColumnConfigLogic
    openAccountTab: (
        accountId: string,
        tab: AccountExpansionTab
    ) => {
        accountId: string
        tab: AccountExpansionTab
    } // accountsExpansionLogic
    setTileFilter: (filter: TileFilter | null) => {
        filter: TileFilter | null
    } // accountsOverviewTilesLogic
    setMineOnly: (mineOnly: boolean) => {
        mineOnly: boolean
    } // customerAnalyticsSceneLogic
    listLoadData: (
        refresh?: RefreshType | undefined,
        alreadyRunningQueryId?: string | undefined,
        overrideQuery?: DataNode<Record<string, any>> | undefined
    ) => {
        overrideQuery: DataNode<Record<string, any>> | undefined
        pollOnly: boolean
        queryId: string
        refresh: RefreshType | undefined
    } // dataNodeLogic
    listLoadNextData: () => any // dataNodeLogic
    ensureAllMembersLoaded: () => {
        value: true
    } // membersLogic
    loadUserSuccess: (
        user: UserType | null,
        payload?:
            | {
                  resetOnFailure: boolean | undefined
              }
            | undefined
    ) => {
        payload?: {
            resetOnFailure: boolean | undefined
        }
        user: UserType | null
    } // userLogic
    addTagToFilter: (tag: string) => {
        tag: string
    }
    openAccount: (
        accountId: string,
        externalId: string | null,
        name: string,
        tab: AccountExpansionTab
    ) => {
        accountId: string
        externalId: string | null
        name: string
        tab: AccountExpansionTab
    }
    refresh: () => {
        value: true
    }
    reportFilterChange: (filterType: AccountFilterType) => {
        filterType: AccountFilterType
    }
    roleUpdateFinished: (
        accountId: string,
        column: string
    ) => {
        accountId: string
        column: string
    }
    roleUpdateStarted: (
        accountId: string,
        column: string
    ) => {
        accountId: string
        column: string
    }
    setAccountFilters: (filters: AccountFilter[]) => {
        filters: AccountFilter[]
    }
    setAccountIdFilter: (accountId: string | null) => {
        accountId: string | null
    }
    setAllRolesUnassigned: (value: boolean) => {
        value: boolean
    }
    setAssignedToCurrentUser: (value: boolean) => {
        value: boolean
    }
    setAssignedToFilter: (value: RoleFilterValue) => {
        value: RoleFilterValue
    }
    setRelationshipOverride: (
        accountId: string,
        column: string,
        userIds: number[]
    ) => {
        accountId: string
        column: string
        userIds: number[]
    }
    setSearchInput: (query: string) => {
        query: string
    }
    setSearchQuery: (query: string) => {
        query: string
    }
    setSortOrder: (sortOrder: AccountSortOrder) => {
        sortOrder: AccountSortOrder
    }
    setTagsFilter: (tags: string[]) => {
        tags: string[]
    }
    setTagsOverride: (
        accountId: string,
        tags: string[] | null
    ) => {
        accountId: string
        tags: string[] | null
    }
    tagsUpdateFinished: (accountId: string) => {
        accountId: string
    }
    tagsUpdateStarted: (accountId: string) => {
        accountId: string
    }
    toggleSort: (column: AccountSortableColumn) => {
        column: string
    }
    updateAccountFilters: (filters: AccountFilter[]) => {
        filters: AccountFilter[]
    }
    updateAccountRole: (
        accountId: string,
        column: string,
        user: UserBasicType | null
    ) => {
        accountId: string
        column: string
        user: UserBasicType | null
    }
    updateAccountTags: (
        accountId: string,
        tags: string[]
    ) => {
        accountId: string
        tags: string[]
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface accountsLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        currentUserId: (user: UserType | null) => number | null
        assignedToCurrentUser: (assignedToFilter: RoleFilterValue, currentUserId: number | null) => boolean
        isRoleSaving: (savingRoles: Record<string, true>) => (accountId: string, column: string) => boolean
        isTagsSaving: (savingTags: Record<string, true>) => (accountId: string) => boolean
        activeFilterCount: (
            searchQuery: string,
            tagsFilter: string[],
            allRolesUnassigned: boolean,
            assignedToFilter: RoleFilterValue,
            accountFilters: AccountFilter[]
        ) => number
        viewUrlState: (
            searchQuery: string,
            tagsFilter: string[],
            allRolesUnassigned: boolean,
            assignedToFilter: RoleFilterValue,
            sortOrder: AccountSortOrder,
            selectColumns: string[],
            defaultSelectColumns: string[],
            tileFilter: TileFilter | null,
            accountFilters: AccountFilter[],
            columnDisplay: AccountColumnDisplayState
        ) => AccountsViewUrlState
        canSortClientSide: (listHasMoreData: boolean, listPaginated: boolean) => boolean
        sortedRowsTransformer: (
            canSortClientSide: boolean,
            sortOrder: AccountSortOrder,
            accountsTableQueryPlan: AccountsTableQueryPlan
        ) => ((rows: DataTableRow[]) => DataTableRow[]) | undefined
        accountsTableQueryPlanInput: (
            querySelectColumns: string[],
            visibleColumnNames: string[],
            searchQuery: string,
            tagsFilter: string[],
            allRolesUnassigned: boolean,
            assignedToFilter: RoleFilterValue,
            accountIdFilter: string | null,
            tileFilter: TileFilter | null,
            accountFilters: AccountFilter[],
            customPropertyDefinitionsById: Record<string, CustomPropertyDefinitionApi>,
            columnDisplay: AccountColumnDisplayState,
            sortOrder: AccountSortOrder,
            canSortClientSide: boolean
        ) => BuildAccountsTableQueryPlanInput
        accountsTableQueryPlan: (
            accountsTableQueryPlanInput: BuildAccountsTableQueryPlanInput
        ) => AccountsTableQueryPlan
        accountsQuerySource: (
            accountsTableQueryPlan: AccountsTableQueryPlan,
            relationshipDefinitionsLoaded: boolean
        ) => AccountsTableQuery | null
        accountsDataTableQuery: (
            accountsTableQueryPlan: AccountsTableQueryPlan,
            accountsQuerySource: AccountsTableQuery | null
        ) => DataTableNode
        metricsQuery: (
            overviewMetrics: AccountsTableMetric[],
            accountsTableQueryPlan: AccountsTableQueryPlan,
            relationshipDefinitionsLoaded: boolean
        ) => AccountsTableQuery | null
    }
}

export type accountsLogicType = MakeLogicType<
    accountsLogicValues,
    accountsLogicActions,
    Record<string, any>,
    accountsLogicMeta
>

export const accountsLogic = kea<accountsLogicType>([
    path(['scenes', 'customerAnalytics', 'accounts', 'accountsLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            userLogic,
            ['user'],
            accountsColumnConfigLogic,
            [
                'selectColumns',
                'defaultSelectColumns',
                'visibleColumnNames',
                'querySelectColumns',
                'aliasToRelationshipDefinition',
                'aliasToDefinition',
                'relationshipDefinitionsLoaded',
                'customPropertyDefinitionsById',
                'columnDisplay',
            ],
            accountsOverviewTilesLogic,
            ['metrics as overviewMetrics', 'tileFilter'],
            customerAnalyticsSceneLogic,
            ['mineOnly'],
            dataNodeLogic({ key: ACCOUNTS_TABLE_DATA_NODE_KEY } as DataNodeLogicProps),
            ['hasMoreData as listHasMoreData'],
        ],
        actions: [
            accountsColumnConfigLogic,
            [
                'loadCustomPropertyDefinitionsSuccess',
                'setSelectColumns',
                'selectColumn',
                'unselectColumn',
                'moveColumn',
                'resetColumns',
                'setColumnDisplay',
                'setColumnDisplayConfig',
            ],
            accountsOverviewTilesLogic,
            ['setTileFilter'],
            accountsExpansionLogic,
            ['openAccountTab'],
            customerAnalyticsSceneLogic,
            ['setMineOnly'],
            userLogic,
            ['loadUserSuccess'],
            membersLogic,
            ['ensureAllMembersLoaded'],
            dataNodeLogic({ key: ACCOUNTS_TABLE_DATA_NODE_KEY } as DataNodeLogicProps),
            ['loadData as listLoadData', 'loadNextData as listLoadNextData'],
        ],
    })),
    actions({
        setSearchInput: (query: string) => ({ query }),
        setSearchQuery: (query: string) => ({ query }),
        setTagsFilter: (tags: string[]) => ({ tags }),
        setAccountFilters: (filters: AccountFilter[]) => ({ filters }),
        updateAccountFilters: (filters: AccountFilter[]) => ({ filters }),
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
        updateAccountRole: (accountId: string, column: string, user: UserBasicType | null) => ({
            accountId,
            column,
            user,
        }),
        roleUpdateStarted: (accountId: string, column: string) => ({ accountId, column }),
        roleUpdateFinished: (accountId: string, column: string) => ({ accountId, column }),
        setRelationshipOverride: (accountId: string, column: string, userIds: number[]) => ({
            accountId,
            column,
            userIds,
        }),
        updateAccountTags: (accountId: string, tags: string[]) => ({ accountId, tags }),
        // Clicking a tag in a row's tags cell adds it to the tags filter (compounding).
        addTagToFilter: (tag: string) => ({ tag }),
        tagsUpdateStarted: (accountId: string) => ({ accountId }),
        tagsUpdateFinished: (accountId: string) => ({ accountId }),
        // null drops the override, falling back to the fetched cell value.
        setTagsOverride: (accountId: string, tags: string[] | null) => ({ accountId, tags }),
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
        accountFilters: [
            [] as AccountFilter[],
            {
                setAccountFilters: (_, { filters }) => filters,
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
        // Keeps server-side sort while paging, so reaching the last page never drops the
        // orderBy and collapses the accumulated rows back to page one. Resetting on every
        // listLoadData is deliberate even for the refetch a sort-while-paginated triggers:
        // that request already carries the new orderBy, and its response replaces the
        // accumulated pages with one server-sorted page that is safe to client-sort next.
        listPaginated: [
            false,
            {
                listLoadData: () => false,
                listLoadNextData: () => true,
            },
        ],
        savingRoles: [
            {} as Record<string, true>,
            {
                roleUpdateStarted: (state, { accountId, column }) => ({
                    ...state,
                    [savingRoleKey(accountId, column)]: true,
                }),
                roleUpdateFinished: (state, { accountId, column }) => {
                    const next = { ...state }
                    delete next[savingRoleKey(accountId, column)]
                    return next
                },
            },
        ],
        // Assignments written from the list, keyed `${accountId}:${column}` — masks the
        // stale fetched cell until the async refetch lands.
        relationshipOverrides: [
            {} as Record<string, number[]>,
            {
                setRelationshipOverride: (state, { accountId, column, userIds }) => ({
                    ...state,
                    [savingRoleKey(accountId, column)]: userIds,
                }),
            },
        ],
        savingTags: [
            {} as Record<string, true>,
            {
                tagsUpdateStarted: (state, { accountId }) => ({ ...state, [accountId]: true }),
                tagsUpdateFinished: (state, { accountId }) => {
                    const next = { ...state }
                    delete next[accountId]
                    return next
                },
            },
        ],
        // Tags written from the list, keyed by account id, mask the stale fetched
        // cell until the async refetch lands.
        tagOverrides: [
            {} as Record<string, string[]>,
            {
                setTagsOverride: (state, { accountId, tags }) => {
                    const next = { ...state }
                    if (tags === null) {
                        delete next[accountId]
                    } else {
                        next[accountId] = tags
                    }
                    return next
                },
            },
        ],
    }),
    selectors({
        currentUserId: [(s) => [s.user], (user: null | import('~/types').UserType): number | null => user?.id ?? null],
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
                (accountId: string, column: string): boolean =>
                    !!savingRoles[savingRoleKey(accountId, column)],
        ],
        isTagsSaving: [
            (s) => [s.savingTags],
            (savingTags: Record<string, true>) =>
                (accountId: string): boolean =>
                    !!savingTags[accountId],
        ],
        activeFilterCount: [
            (s) => [s.searchQuery, s.tagsFilter, s.allRolesUnassigned, s.assignedToFilter, s.accountFilters],
            (
                searchQuery: string,
                tagsFilter: string[],
                allRolesUnassigned: boolean,
                assignedToFilter: RoleFilterValue,
                accountFilters: AccountFilter[]
            ): number =>
                [
                    !!searchQuery.trim(),
                    tagsFilter.length > 0,
                    allRolesUnassigned,
                    assignedToFilter.length > 0,
                    accountFilters.length > 0,
                ].filter(Boolean).length,
        ],
        viewUrlState: [
            (s) => [
                s.searchQuery,
                s.tagsFilter,
                s.allRolesUnassigned,
                s.assignedToFilter,
                s.sortOrder,
                s.selectColumns,
                s.defaultSelectColumns,
                s.tileFilter,
                s.accountFilters,
                s.columnDisplay,
            ],
            (
                searchQuery: string,
                tagsFilter: string[],
                allRolesUnassigned: boolean,
                assignedToFilter: RoleFilterValue,
                sortOrder: AccountSortOrder,
                selectColumns: string[],
                defaultSelectColumns: string[],
                tileFilter: TileFilter | null,
                accountFilters: AccountFilter[],
                columnDisplay: AccountColumnDisplayState
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
                if (!objectsEqual(selectColumns, defaultSelectColumns)) {
                    state.columns = selectColumns
                }
                if (Object.keys(columnDisplay).length > 0) {
                    state.columnDisplay = columnDisplay
                }
                if (tileFilter) {
                    state.tileFilter = tileFilter
                }
                if (accountFilters.length > 0) {
                    state.customProperties = accountFilters
                }
                return state
            },
        ],
        canSortClientSide: [
            (s) => [s.listHasMoreData, s.listPaginated],
            (listHasMoreData: boolean, listPaginated: boolean): boolean => !listHasMoreData && !listPaginated,
        ],
        sortedRowsTransformer: [
            (s) => [s.canSortClientSide, s.sortOrder, s.accountsTableQueryPlan],
            (
                canSortClientSide: boolean,
                sortOrder: AccountSortOrder,
                plan: AccountsTableQueryPlan
            ): ((rows: DataTableRow[]) => DataTableRow[]) | undefined =>
                canSortClientSide && sortOrder
                    ? (rows: DataTableRow[]): DataTableRow[] =>
                          sortAccountRows(rows, sortOrder, (record, column) =>
                              isAccountsTableRow(record) ? accountsTableCell(record, column, plan) : undefined
                          )
                    : undefined,
        ],
        accountsTableQueryPlanInput: [
            (s) => [
                s.querySelectColumns,
                s.visibleColumnNames,
                s.searchQuery,
                s.tagsFilter,
                s.allRolesUnassigned,
                s.assignedToFilter,
                s.accountIdFilter,
                s.tileFilter,
                s.accountFilters,
                s.customPropertyDefinitionsById,
                s.columnDisplay,
                s.sortOrder,
                s.canSortClientSide,
            ],
            (
                querySelectColumns: string[],
                visibleColumnNames: string[],
                searchQuery: string,
                tagsFilter: string[],
                allRolesUnassigned: boolean,
                assignedToFilter: RoleFilterValue,
                accountIdFilter: string | null,
                tileFilter: TileFilter | null,
                accountFilters: AccountFilter[],
                customPropertyDefinitionsById: Record<string, CustomPropertyDefinitionApi>,
                columnDisplay: AccountColumnDisplayState,
                sortOrder: AccountSortOrder,
                canSortClientSide: boolean
            ): BuildAccountsTableQueryPlanInput => ({
                querySelectColumns,
                visibleColumnNames,
                searchQuery,
                tagsFilter,
                allRolesUnassigned,
                assignedToFilter,
                accountIdFilter,
                tileFilter,
                accountFilters,
                customPropertyDefinitionsById,
                columnDisplay,
                sortOrder,
                canSortClientSide,
            }),
        ],
        accountsTableQueryPlan: [
            (s) => [s.accountsTableQueryPlanInput],
            (input: BuildAccountsTableQueryPlanInput): AccountsTableQueryPlan => buildAccountsTableQueryPlan(input),
        ],
        accountsQuerySource: [
            (s) => [s.accountsTableQueryPlan, s.relationshipDefinitionsLoaded],
            (
                accountsTableQueryPlan: AccountsTableQueryPlan,
                relationshipDefinitionsLoaded: boolean
            ): AccountsTableQuery | null => (relationshipDefinitionsLoaded ? accountsTableQueryPlan.query : null),
        ],
        accountsDataTableQuery: [
            (s) => [s.accountsTableQueryPlan, s.accountsQuerySource],
            (
                accountsTableQueryPlan: AccountsTableQueryPlan,
                accountsQuerySource: AccountsTableQuery | null
            ): DataTableNode => ({
                kind: NodeKind.DataTableNode,
                columns: accountsTableQueryPlan.columns.map((column) => column.visibleName),
                source: accountsQuerySource ?? accountsTableQueryPlan.query,
                full: true,
                allowSorting: true,
            }),
        ],
        metricsQuery: [
            (s) => [s.overviewMetrics, s.accountsTableQueryPlan, s.relationshipDefinitionsLoaded],
            (
                overviewMetrics: AccountsTableMetric[],
                accountsTableQueryPlan: AccountsTableQueryPlan,
                relationshipDefinitionsLoaded: boolean
            ): AccountsTableQuery | null => {
                if (overviewMetrics.length === 0 || !relationshipDefinitionsLoaded) {
                    return null
                }
                return {
                    ...accountsTableQueryPlan.query,
                    columns: [],
                    metrics: overviewMetrics,
                    sort: undefined,
                    tags: { ...CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS, name: 'customer_analytics_accounts_overview' },
                }
            },
        ],
    }),
    listeners(({ actions, values, cache, selectors }) => ({
        loadCustomPropertyDefinitionsSuccess: ({ customPropertyDefinitions }) => {
            cache.customPropertyDefinitionsLoaded = true
            const definitionsById = Object.fromEntries(
                customPropertyDefinitions.map((definition) => [definition.id, definition])
            )
            const supportedFilters = supportedAccountFilters(values.accountFilters, definitionsById)
            if (!objectsEqual(supportedFilters, values.accountFilters)) {
                actions.setAccountFilters(supportedFilters)
            }
        },
        setAccountFilters: ({ filters }) => {
            if (!cache.customPropertyDefinitionsLoaded) {
                return
            }
            const supportedFilters = supportedAccountFilters(filters, values.customPropertyDefinitionsById)
            if (!objectsEqual(supportedFilters, filters)) {
                actions.setAccountFilters(supportedFilters)
            }
        },
        updateAccountFilters: ({ filters }, _, __, previousState) => {
            const supportedFilters = cache.customPropertyDefinitionsLoaded
                ? supportedAccountFilters(filters, values.customPropertyDefinitionsById)
                : filters
            const previousFilters = selectors.accountFilters(previousState)
            const changedFilter =
                supportedFilters.find((filter, index) => !objectsEqual(filter, previousFilters[index])) ??
                previousFilters.find((filter, index) => !objectsEqual(filter, supportedFilters[index]))
            actions.setAccountFilters(supportedFilters)
            const fieldKind = changedFilter?.type === 'account' ? 'account_field' : 'custom_property'
            posthog.capture(AccountsEvents.FilterChanged, {
                filter_type: fieldKind,
                field_kind: fieldKind,
                operator: changedFilter?.operator,
                filter_count: supportedFilters.length,
                is_cleared: supportedFilters.length === 0,
                active_filter_count: values.activeFilterCount,
            })
        },
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
            // Keep the shared "mine only" toggle in step with the assigned-to filter
            // (set via the "My accounts" shortcut or the assigned-to picker) so
            // switching to the Notes tab reflects the same choice.
            actions.setMineOnly(values.assignedToCurrentUser)
        },
        // The "My accounts" restore needs the current user's id. On a fresh page load this
        // logic can mount before userLogic resolves the user (currentUserId still null during
        // URL restore), so the persisted choice can't be applied then. Re-apply it once the
        // user arrives — only when the URL carried no explicit assignment and nothing else has
        // set the filter, so a shared link or an explicit pick always wins.
        loadUserSuccess: () => {
            if (
                values.mineOnly &&
                values.currentUserId !== null &&
                !values.assignedToFilter.length &&
                !values.allRolesUnassigned
            ) {
                actions.setAssignedToFilter([values.currentUserId])
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
            dataNodeLogic.findMounted({ key: ACCOUNTS_TABLE_DATA_NODE_KEY })?.actions.loadData('force_async')
            dataNodeLogic.findMounted({ key: ACCOUNTS_METRICS_DATA_NODE_KEY })?.actions.loadData('force_async')
        },
        updateAccountRole: async ({ accountId, column, user }) => {
            if (values.isRoleSaving(accountId, column)) {
                return
            }
            const definition = values.aliasToRelationshipDefinition[column]
            if (!definition) {
                return
            }
            const projectId = String(values.currentTeamId)
            actions.roleUpdateStarted(accountId, column)
            try {
                if (user) {
                    // Assigning a single-holder relationship ends the current holder server-side.
                    await accountsRelationshipsCreate(projectId, accountId, {
                        definition: definition.id,
                        user: user.id,
                    })
                } else {
                    const active = await accountsRelationshipsList(projectId, accountId)
                    await Promise.all(
                        active
                            .filter((relationship) => relationship.definition.id === definition.id)
                            .map((relationship) =>
                                accountsRelationshipsEndCreate(projectId, accountId, relationship.id)
                            )
                    )
                }
                actions.setRelationshipOverride(accountId, column, user ? [user.id] : [])
                posthog.capture(AccountsEvents.RoleAssigned, {
                    role: isLegacyRoleColumn(column) ? column : definition.name,
                    is_assigned: user !== null,
                    assigned_user_id: user?.id ?? null,
                    source: 'list_row',
                })
                dataNodeLogic.findMounted({ key: ACCOUNTS_TABLE_DATA_NODE_KEY })?.actions.loadData('force_async')
                dataNodeLogic.findMounted({ key: ACCOUNTS_METRICS_DATA_NODE_KEY })?.actions.loadData('force_async')
            } catch (error) {
                posthog.captureException(error as Error, { scope: 'accountsLogic.updateAccountRole' })
                lemonToast.error(`Failed to update ${definition.name}`)
            } finally {
                actions.roleUpdateFinished(accountId, column)
            }
        },
        addTagToFilter: ({ tag }) => {
            if (values.tagsFilter.includes(tag)) {
                return
            }
            actions.setTagsFilter([...values.tagsFilter, tag])
            actions.reportFilterChange('tag')
        },
        updateAccountTags: async ({ accountId, tags }, breakpoint) => {
            const previous = values.tagOverrides[accountId] ?? null
            // Optimistic: ObjectTags is a controlled input firing per added/removed tag,
            // so its value must reflect each change immediately or the editor reverts.
            actions.setTagsOverride(accountId, tags)
            // ponytail: the breakpoint is per-action, not per-account — editing two
            // accounts' tags within 300ms drops the first save. Key it per account if
            // that ever becomes a real interaction.
            await breakpoint(TAGS_SAVE_DEBOUNCE_MS)
            actions.tagsUpdateStarted(accountId)
            try {
                await accountsPartialUpdate(String(values.currentTeamId), accountId, { tags })
                posthog.capture(AccountsEvents.TagsUpdated, { tag_count: tags.length })
                // A newly created tag should show up in the available-tags pickers right away.
                tagsModel.findMounted()?.actions.loadTags()
                dataNodeLogic.findMounted({ key: ACCOUNTS_TABLE_DATA_NODE_KEY })?.actions.loadData('force_async')
                dataNodeLogic.findMounted({ key: ACCOUNTS_METRICS_DATA_NODE_KEY })?.actions.loadData('force_async')
            } catch (error) {
                actions.setTagsOverride(accountId, previous)
                posthog.captureException(error as Error, { scope: 'accountsLogic.updateAccountTags' })
                lemonToast.error('Failed to update tags')
            } finally {
                actions.tagsUpdateFinished(accountId)
            }
        },
        openAccount: ({ accountId, externalId, name, tab }) => {
            const dataNode = dataNodeLogic.findMounted({ key: ACCOUNTS_TABLE_DATA_NODE_KEY })
            const results = (dataNode?.values.response as { results?: unknown[] } | undefined)?.results
            const rows = Array.isArray(results) ? results : []
            const isVisible = rows.some(
                (row) =>
                    row && typeof row === 'object' && !Array.isArray(row) && (row as { id?: string }).id === accountId
            )
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
                if (values.accountFilters.length > 0) {
                    actions.setAccountFilters([])
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
    afterMount(({ actions }) => {
        posthog.capture(AccountsEvents.ListViewed)
        // Relationship cells resolve assigned user ids against the org member list,
        // so it must be loaded up front rather than on first dropdown open.
        actions.ensureAllMembersLoaded()
    }),
    actionToUrl(({ values }) => {
        // Mirror the full view into the URL hash so the link is shareable.
        // Search params are preserved untouched — the parent scene owns those.
        const toUrl = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] => [
            accountsPathToWriteBackTo(values.accountIdFilter),
            router.values.searchParams,
            objectsEqual(values.viewUrlState, {}) ? {} : { view: values.viewUrlState },
            { replace: true },
        ]
        return {
            setSearchQuery: toUrl,
            setTagsFilter: toUrl,
            setAccountFilters: toUrl,
            setAllRolesUnassigned: toUrl,
            setAssignedToFilter: toUrl,
            setSortOrder: toUrl,
            setSelectColumns: toUrl,
            selectColumn: toUrl,
            unselectColumn: toUrl,
            moveColumn: toUrl,
            resetColumns: toUrl,
            setColumnDisplay: toUrl,
            setColumnDisplayConfig: toUrl,
            setTileFilter: toUrl,
        }
    }),
    urlToAction(({ actions, values }) => {
        // Path route `/accounts/:accountId/:tab`: filter the list to one account and open the tab.
        // The URL stays on the path — neither setter is wired into actionToUrl, and the setters that
        // are keep the current path (see `accountsPathToWriteBackTo`).
        const openAccountByPath = (accountId: string | undefined, rawTab?: string): void => {
            // Invalid path ids must not reach the typed account filter.
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
        const restoreView = (view: AccountsViewUrlState): void => {
            const search = view.search ?? ''
            if (search !== values.searchQuery) {
                actions.setSearchQuery(search)
            }

            const tags = view.tags ?? []
            if (!objectsEqual(tags, values.tagsFilter)) {
                actions.setTagsFilter(tags)
            }

            const customProperties = Array.isArray(view.customProperties) ? view.customProperties : []
            if (!objectsEqual(customProperties, values.accountFilters)) {
                actions.setAccountFilters(customProperties)
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
            // With no explicit assignment in the hash (e.g. arriving via the tab
            // link), fall back to the shared "mine only" toggle so the choice made
            // on the Notes tab carries over.
            const sharedMine =
                !assignedTo.length && !view.mine && values.mineOnly && values.currentUserId !== null
                    ? [values.currentUserId]
                    : []
            // The persisted "my accounts" intent can't be resolved until the user id is
            // known. If the user hasn't loaded yet, leave the filter untouched (rather than
            // writing an empty one, which would cascade to setMineOnly(false) and clobber the
            // preference) and let the loadUserSuccess listener apply it once the user resolves.
            const mineRestorePending =
                !assignedTo.length && !view.mine && values.mineOnly && values.currentUserId === null
            const nextAssignedTo = assignedTo.length ? assignedTo : legacyMine.length ? legacyMine : sharedMine
            if (!mineRestorePending && !objectsEqual(nextAssignedTo, values.assignedToFilter)) {
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

            const columnDisplay = view.columnDisplay && typeof view.columnDisplay === 'object' ? view.columnDisplay : {}
            if (!objectsEqual(columnDisplay, values.columnDisplay)) {
                actions.setColumnDisplayConfig(columnDisplay)
            }

            const tileFilter = view.tileFilter ?? null
            if (!objectsEqual(tileFilter, values.tileFilter)) {
                actions.setTileFilter(tileFilter)
            }
        }
        const viewFromHash = (hashParams: Record<string, any> | undefined): AccountsViewUrlState =>
            hashParams?.view && typeof hashParams.view === 'object' ? hashParams.view : {}
        return {
            [urls.customerAnalyticsAccounts()]: (_, __, hashParams): void => {
                restoreView(viewFromHash(hashParams))

                // Back on the bare list — drop any single-account path filter.
                if (values.accountIdFilter !== null) {
                    actions.setAccountIdFilter(null)
                }
            },
            // A deep link carries the same shareable `#view=` hash, but only restore it when it's
            // actually there — an absent hash on this route means "just open the account", not
            // "reset the list", so the saved view stays in charge.
            [urls.customerAnalyticsAccount(':accountId')]: ({ accountId }, __, hashParams): void => {
                if (hashParams?.view) {
                    restoreView(viewFromHash(hashParams))
                }
                openAccountByPath(accountId)
            },
            [urls.customerAnalyticsAccount(':accountId', ':tab')]: ({ accountId, tab }, __, hashParams): void => {
                if (hashParams?.view) {
                    restoreView(viewFromHash(hashParams))
                }
                openAccountByPath(accountId, tab)
            },
        }
    }),
])
