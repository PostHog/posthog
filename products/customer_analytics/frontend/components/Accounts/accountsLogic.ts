import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import {
    type AssignmentStatus,
    isAssignmentStatus,
} from 'lib/components/AccountAssignmentFilter/accountAssignmentFilterTypes'
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
    accountsCustomPropertyValuesCreate,
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
import type {
    AccountRelationshipDefinitionApi,
    CustomPropertyDefinitionApi,
    CustomPropertyValueWriteApi,
} from '../../generated/api.schemas'
import { accountsColumnConfigLogic, isLegacyRoleColumn } from './accountsColumnConfigLogic'
import type { AccountColumnDisplayState } from './accountsColumnConfigLogic'
import {
    ACCOUNT_EXPANSION_TABS,
    AccountExpansionTab,
    accountsExpansionLogic,
    DEFAULT_ACCOUNT_TAB,
} from './accountsExpansionLogic'
import { accountsOverviewTilesLogic, TileFilter } from './accountsOverviewTilesLogic'
import type { AccountsOverviewTile } from './accountsOverviewTilesLogic'
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
import {
    AccountsViewState,
    normalizeRoleFilter,
    readAccountsViewDraft,
    writeAccountsViewDraft,
} from './accountsViewState'
import { AccountsEvents, DEFAULT_TILES } from './constants'

export const SEARCH_DEBOUNCE_MS = 300

// Debounce tag edits because ObjectTags emits each addition and removal separately.
export const TAGS_SAVE_DEBOUNCE_MS = 300

// Wait for refetched rows before scrolling to an account.
const SCROLL_TO_ACCOUNT_POLL_MS = 100
const SCROLL_TO_ACCOUNT_MAX_ATTEMPTS = 40

interface SortLikeValues {
    sortOrder: AccountSortOrder
    visibleColumnNames: string[]
}

interface SortLikeActions {
    setSortOrder: (sortOrder: AccountSortOrder) => void
}

// A removed column cannot supply a client sort key or a typed server sort reference.
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

export type AccountFilterType = 'tag' | 'assignment_status' | 'my_accounts' | 'assigned_to'

export type AccountSortableColumn = string

export type AccountSortDirection = 'asc' | 'desc'

export type AccountSortOrder = { column: AccountSortableColumn; direction: AccountSortDirection } | null

export const savingRoleKey = (accountId: string, column: string): string => `${accountId}:${column}`

export const customPropertySavingKey = (accountId: string, definitionId: string): string =>
    `${accountId}:${definitionId}`

// Late list updates must not leave an account detail route or navigate back from another scene.
function accountsPathToWriteBackTo(accountIdFilter: string | null): string | null {
    const pathname = removeProjectIdIfPresent(router.values.location.pathname)
    if (pathname === urls.customerAnalyticsAccounts()) {
        return pathname
    }
    const deepLinkPath = accountIdFilter ? urls.customerAnalyticsAccount(accountIdFilter) : null
    return deepLinkPath && pathname.startsWith(deepLinkPath) ? pathname : null
}

function isAccountsListPath(): boolean {
    return removeProjectIdIfPresent(router.values.location.pathname) === urls.customerAnalyticsAccounts()
}

function hasSharedView(hashParams: Record<string, any> | undefined): boolean {
    return (
        !!hashParams &&
        typeof hashParams.view === 'object' &&
        hashParams.view !== null &&
        !Array.isArray(hashParams.view)
    )
}

interface AccountsViewDraftIdentity {
    teamId: number
    userId: string
}

function getAccountsViewDraftIdentity(
    currentTeamId: number | null,
    user: UserType | null
): AccountsViewDraftIdentity | null {
    return currentTeamId !== null && user?.uuid ? { teamId: currentTeamId, userId: user.uuid } : null
}

function persistViewStateAndUrl(
    actions: { persistViewState: (search?: string) => unknown; syncViewStateToUrl: () => unknown },
    isRestoring: boolean,
    viewStateHydrated: boolean
): void {
    if (isRestoring || !viewStateHydrated) {
        return
    }
    actions.persistViewState()
    actions.syncViewStateToUrl()
}

export interface AccountsViewUrlState {
    search?: string
    tags?: string[]
    /** Legacy nonempty links without a status remain assigned-only. */
    assignmentStatus?: AssignmentStatus
    /** @deprecated Legacy unassigned-only flag; still read for old shared links. Never written. */
    unassigned?: boolean
    /** Concrete user IDs make shared links independent of the viewer. */
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

export type AccountsViewStateSource = 'defaults' | 'draft' | 'saved_view' | 'shared_url'

export interface ApplyAccountsViewStateOptions {
    source: AccountsViewStateSource
    columns: 'restore' | 'defaults' | 'keep'
}

function viewStateWithMineOnly(
    viewState: AccountsViewState,
    mineOnly: boolean,
    currentUserId: number | null
): AccountsViewState {
    if (currentUserId === null) {
        return viewState
    }
    const assignedToCurrentUser =
        viewState.filters.assignedTo.length === 1 && viewState.filters.assignedTo[0] === currentUserId
    if (mineOnly) {
        return {
            ...viewState,
            filters: { ...viewState.filters, assignmentStatus: 'assigned', assignedTo: [currentUserId] },
        }
    }
    return assignedToCurrentUser ? { ...viewState, filters: { ...viewState.filters, assignedTo: [] } } : viewState
}

function accountsViewStateFromUrl(
    view: AccountsViewUrlState,
    defaultColumns: string[],
    currentUserId: number | null,
    tiles: AccountsOverviewTile[]
): AccountsViewState {
    const explicitStatus = isAssignmentStatus(view.assignmentStatus) ? view.assignmentStatus : undefined
    const assignedTo = normalizeRoleFilter(view.assignedTo)
    const legacyMine = !assignedTo.length && view.mine && currentUserId !== null ? [currentUserId] : []
    const hasViewKeys = Object.keys(view).length > 0
    const assignmentStatus: AssignmentStatus = explicitStatus
        ? explicitStatus
        : hasViewKeys
          ? view.unassigned
              ? 'unassigned'
              : 'assigned'
          : 'all'
    return {
        columns:
            Array.isArray(view.columns) && view.columns.every((column) => typeof column === 'string')
                ? view.columns
                : defaultColumns,
        sortOrder:
            view.sort &&
            typeof view.sort.column === 'string' &&
            (view.sort.direction === 'asc' || view.sort.direction === 'desc')
                ? view.sort
                : null,
        filters: {
            search: typeof view.search === 'string' ? view.search : '',
            assignmentStatus,
            assignedTo: assignmentStatus === 'assigned' ? (assignedTo.length ? assignedTo : legacyMine) : [],
            tags: Array.isArray(view.tags) ? view.tags.filter((tag): tag is string => typeof tag === 'string') : [],
            tileFilter: view.tileFilter && typeof view.tileFilter === 'object' ? view.tileFilter : null,
            customProperties: Array.isArray(view.customProperties) ? view.customProperties : [],
        },
        tiles,
        columnDisplay: view.columnDisplay && typeof view.columnDisplay === 'object' ? view.columnDisplay : {},
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface accountsLogicValues {
    aliasToDefinition: Record<string, CustomPropertyDefinitionApi> // accountsColumnConfigLogic
    aliasToRelationshipDefinition: Record<string, AccountRelationshipDefinitionApi> // accountsColumnConfigLogic
    columnDisplay: AccountColumnDisplayState // accountsColumnConfigLogic
    customPropertyDefinitionsById: Record<string, CustomPropertyDefinitionApi> // accountsColumnConfigLogic
    defaultSelectColumns: string[] // accountsColumnConfigLogic
    querySelectColumns: string[] // accountsColumnConfigLogic
    relationshipDefinitionsById: Record<string, AccountRelationshipDefinitionApi> // accountsColumnConfigLogic
    relationshipDefinitionsLoaded: boolean // accountsColumnConfigLogic
    selectColumns: string[] // accountsColumnConfigLogic
    visibleColumnNames: string[] // accountsColumnConfigLogic
    overviewMetrics: AccountsTableMetric[] // accountsOverviewTilesLogic
    tileFilter: TileFilter | null // accountsOverviewTilesLogic
    tiles: AccountsOverviewTile[] // accountsOverviewTilesLogic
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
    assignedToCurrentUser: boolean
    assignedToFilter: RoleFilterValue
    assignmentStatus: AssignmentStatus
    awaitingSavedView: boolean
    canSortClientSide: boolean
    currentUserId: number | null
    customPropertyOverrides: Record<string, CustomPropertyValueWriteApi['value']>
    draftRestored: boolean
    isCustomPropertySaving: (accountId: string, definitionId: string) => boolean
    isRoleSaving: (accountId: string, column: string) => boolean
    isTagsSaving: (accountId: string) => boolean
    listPaginated: boolean
    metricsQuery: AccountsTableQuery | null
    relationshipOverrides: Record<string, number[]>
    savingCustomProperties: Record<string, true>
    savingRoles: Record<string, true>
    savingTags: Record<string, true>
    searchInput: string
    searchQuery: string
    sortOrder: AccountSortOrder
    sortedRowsTransformer: ((rows: DataTableRow[]) => DataTableRow[]) | undefined
    tagOverrides: Record<string, string[]>
    tagsFilter: string[]
    viewState: AccountsViewState
    viewStateHydrated: boolean
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
    loadRelationshipDefinitionsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    } // accountsColumnConfigLogic
    loadRelationshipDefinitionsSuccess: (
        relationshipDefinitions: AccountRelationshipDefinitionApi[],
        payload?: any
    ) => {
        payload?: any
        relationshipDefinitions: AccountRelationshipDefinitionApi[]
    } // accountsColumnConfigLogic
    resetColumns: () => {
        value: true
    } // accountsColumnConfigLogic
    restoreSelectColumns: (columns: string[]) => {
        columns: string[]
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
    setTiles: (tiles: AccountsOverviewTile[]) => {
        tiles: AccountsOverviewTile[]
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
    listLoadDataSuccess: (
        response:
            | Record<string, any>
            | null
            | import('~/queries/schema').ErrorTrackingQueryResponse
            | import('~/queries/schema').HogQLAutocompleteResponse
            | import('~/queries/schema').HogQLMetadataResponse
            | import('~/queries/schema').HogQLQueryResponse<any[]>
            | import('~/queries/schema').HogQueryResponse
            | import('~/queries/schema').LogAttributesQueryResponse
            | import('~/queries/schema').LogValuesQueryResponse
            | import('~/queries/schema').MetricsQueryResponse
            | import('~/queries/schema').SessionsQueryResponse
            | import('~/queries/schema').TraceSpansAggregationQueryResponse
            | import('~/queries/schema').TraceSpansAttributeBreakdownQueryResponse
            | import('~/queries/schema').TraceSpansQueryResponse
            | undefined,
        payload?:
            | {
                  overrideQuery: DataNode<Record<string, any>> | undefined
                  pollOnly: boolean
                  queryId: string
                  refresh: RefreshType | undefined
              }
            | undefined
    ) => {
        payload?: {
            overrideQuery: DataNode<Record<string, any>> | undefined
            pollOnly: boolean
            queryId: string
            refresh: RefreshType | undefined
        }
        response:
            | Record<string, any>
            | null
            | import('~/queries/schema').ErrorTrackingQueryResponse
            | import('~/queries/schema').HogQLAutocompleteResponse
            | import('~/queries/schema').HogQLMetadataResponse
            | import('~/queries/schema').HogQLQueryResponse<any[]>
            | import('~/queries/schema').HogQueryResponse
            | import('~/queries/schema').LogAttributesQueryResponse
            | import('~/queries/schema').LogValuesQueryResponse
            | import('~/queries/schema').MetricsQueryResponse
            | import('~/queries/schema').SessionsQueryResponse
            | import('~/queries/schema').TraceSpansAggregationQueryResponse
            | import('~/queries/schema').TraceSpansAttributeBreakdownQueryResponse
            | import('~/queries/schema').TraceSpansQueryResponse
            | undefined
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
    applyViewState: (
        viewState: AccountsViewState,
        options: ApplyAccountsViewStateOptions
    ) => {
        options: ApplyAccountsViewStateOptions
        viewState: AccountsViewState
    }
    clearCustomPropertyOverrides: () => {
        value: true
    }
    customPropertyUpdateFinished: (
        accountId: string,
        definitionId: string
    ) => {
        accountId: string
        definitionId: string
    }
    customPropertyUpdateStarted: (
        accountId: string,
        definitionId: string
    ) => {
        accountId: string
        definitionId: string
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
    persistViewState: (search?: string) => {
        search: string | undefined
    }
    refresh: () => {
        value: true
    }
    reportFilterChange: (filterType: AccountFilterType) => {
        filterType: AccountFilterType
    }
    restoreViewStateFromRoute: (method?: 'POP' | 'PUSH' | 'REPLACE') => {
        method: 'POP' | 'PUSH' | 'REPLACE' | undefined
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
    setAssignedToCurrentUser: (value: boolean) => {
        value: boolean
    }
    setAssignedToFilter: (value: RoleFilterValue) => {
        value: RoleFilterValue
    }
    setAssignmentStatus: (status: AssignmentStatus) => {
        status: AssignmentStatus
    }
    setAwaitingSavedView: (awaiting: boolean) => {
        awaiting: boolean
    }
    setCustomPropertyOverride: (
        accountId: string,
        definitionId: string,
        value: CustomPropertyValueWriteApi['value'] | null
    ) => {
        accountId: string
        definitionId: string
        value: boolean | number | string | null
    }
    setDraftRestored: (restored: boolean) => {
        restored: boolean
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
    setViewStateHydrated: (hydrated: boolean) => {
        hydrated: boolean
    }
    syncViewStateToUrl: () => {
        value: true
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
    updateAccountCustomProperty: (
        accountId: string,
        definition: CustomPropertyDefinitionApi,
        value: CustomPropertyValueWriteApi['value']
    ) => {
        accountId: string
        definition: CustomPropertyDefinitionApi
        value: boolean | number | string | null
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
        isCustomPropertySaving: (
            savingCustomProperties: Record<string, true>
        ) => (accountId: string, definitionId: string) => boolean
        isRoleSaving: (savingRoles: Record<string, true>) => (accountId: string, column: string) => boolean
        isTagsSaving: (savingTags: Record<string, true>) => (accountId: string) => boolean
        activeFilterCount: (
            searchQuery: string,
            tagsFilter: string[],
            assignmentStatus: AssignmentStatus,
            accountFilters: AccountFilter[]
        ) => number
        viewState: (
            selectColumns: string[],
            searchQuery: string,
            tagsFilter: string[],
            assignmentStatus: AssignmentStatus,
            assignedToFilter: RoleFilterValue,
            sortOrder: AccountSortOrder,
            tileFilter: TileFilter | null,
            tiles: AccountsOverviewTile[],
            accountFilters: AccountFilter[],
            columnDisplay: AccountColumnDisplayState
        ) => AccountsViewState
        viewUrlState: (
            searchQuery: string,
            tagsFilter: string[],
            assignmentStatus: AssignmentStatus,
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
            assignmentStatus: AssignmentStatus,
            assignedToFilter: RoleFilterValue,
            accountIdFilter: string | null,
            tileFilter: TileFilter | null,
            accountFilters: AccountFilter[],
            relationshipDefinitionsById: Record<string, AccountRelationshipDefinitionApi>,
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
            relationshipDefinitionsLoaded: boolean,
            awaitingSavedView: boolean,
            viewStateHydrated: boolean
        ) => AccountsTableQuery | null
        accountsDataTableQuery: (
            accountsTableQueryPlan: AccountsTableQueryPlan,
            accountsQuerySource: AccountsTableQuery | null
        ) => DataTableNode
        metricsQuery: (
            overviewMetrics: AccountsTableMetric[],
            accountsTableQueryPlan: AccountsTableQueryPlan,
            relationshipDefinitionsLoaded: boolean,
            awaitingSavedView: boolean,
            viewStateHydrated: boolean
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
                'relationshipDefinitionsById',
                'relationshipDefinitionsLoaded',
                'customPropertyDefinitionsById',
                'columnDisplay',
            ],
            accountsOverviewTilesLogic,
            ['metrics as overviewMetrics', 'tileFilter', 'tiles'],
            customerAnalyticsSceneLogic,
            ['mineOnly'],
            dataNodeLogic({ key: ACCOUNTS_TABLE_DATA_NODE_KEY } as DataNodeLogicProps),
            ['hasMoreData as listHasMoreData'],
        ],
        actions: [
            accountsColumnConfigLogic,
            [
                'loadCustomPropertyDefinitionsSuccess',
                'loadRelationshipDefinitionsSuccess',
                'loadRelationshipDefinitionsFailure',
                'setSelectColumns',
                'selectColumn',
                'unselectColumn',
                'resetColumns',
                'restoreSelectColumns',
                'setColumnDisplay',
                'setColumnDisplayConfig',
            ],
            accountsOverviewTilesLogic,
            ['setTileFilter', 'setTiles'],
            accountsExpansionLogic,
            ['openAccountTab'],
            customerAnalyticsSceneLogic,
            ['setMineOnly'],
            userLogic,
            ['loadUserSuccess'],
            membersLogic,
            ['ensureAllMembersLoaded'],
            dataNodeLogic({ key: ACCOUNTS_TABLE_DATA_NODE_KEY } as DataNodeLogicProps),
            ['loadData as listLoadData', 'loadDataSuccess as listLoadDataSuccess', 'loadNextData as listLoadNextData'],
        ],
    })),
    actions({
        setSearchInput: (query: string) => ({ query }),
        setSearchQuery: (query: string) => ({ query }),
        applyViewState: (viewState: AccountsViewState, options: ApplyAccountsViewStateOptions) => ({
            viewState,
            options,
        }),
        persistViewState: (search?: string) => ({ search }),
        syncViewStateToUrl: true,
        setTagsFilter: (tags: string[]) => ({ tags }),
        setAccountFilters: (filters: AccountFilter[]) => ({ filters }),
        updateAccountFilters: (filters: AccountFilter[]) => ({ filters }),
        setAssignmentStatus: (status: AssignmentStatus) => ({ status }),
        setAssignedToFilter: (value: RoleFilterValue) => ({ value }),
        setAssignedToCurrentUser: (value: boolean) => ({ value }),
        setSortOrder: (sortOrder: AccountSortOrder) => ({ sortOrder }),
        toggleSort: (column: AccountSortableColumn) => ({ column }),
        refresh: true,
        restoreViewStateFromRoute: (method?: 'POP' | 'PUSH' | 'REPLACE') => ({ method }),
        // Separate user interactions from restore actions so restores do not emit filter-change events.
        reportFilterChange: (filterType: AccountFilterType) => ({ filterType }),
        updateAccountCustomProperty: (
            accountId: string,
            definition: CustomPropertyDefinitionApi,
            value: CustomPropertyValueWriteApi['value']
        ) => ({ accountId, definition, value }),
        customPropertyUpdateStarted: (accountId: string, definitionId: string) => ({ accountId, definitionId }),
        customPropertyUpdateFinished: (accountId: string, definitionId: string) => ({ accountId, definitionId }),
        clearCustomPropertyOverrides: true,
        setCustomPropertyOverride: (
            accountId: string,
            definitionId: string,
            value: CustomPropertyValueWriteApi['value'] | null
        ) => ({ accountId, definitionId, value }),
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
        addTagToFilter: (tag: string) => ({ tag }),
        tagsUpdateStarted: (accountId: string) => ({ accountId }),
        tagsUpdateFinished: (accountId: string) => ({ accountId }),
        setTagsOverride: (accountId: string, tags: string[] | null) => ({ accountId, tags }),
        openAccount: (accountId: string, externalId: string | null, name: string, tab: AccountExpansionTab) => ({
            accountId,
            externalId,
            name,
            tab,
        }),
        setAccountIdFilter: (accountId: string | null) => ({ accountId }),
        setAwaitingSavedView: (awaiting: boolean) => ({ awaiting }),
        setDraftRestored: (restored: boolean) => ({ restored }),
        setViewStateHydrated: (hydrated: boolean) => ({ hydrated }),
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
        assignmentStatus: [
            'all' as AssignmentStatus,
            {
                setAssignmentStatus: (_, { status }) => status,
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
        awaitingSavedView: [
            false,
            {
                setAwaitingSavedView: (_, { awaiting }) => awaiting,
            },
        ],
        draftRestored: [
            false,
            {
                setDraftRestored: (_, { restored }) => restored,
            },
        ],
        viewStateHydrated: [
            false,
            {
                setViewStateHydrated: (_, { hydrated }) => hydrated,
            },
        ],
        sortOrder: [
            null as AccountSortOrder,
            {
                setSortOrder: (_, { sortOrder }) => sortOrder,
            },
        ],
        // Keep server sorting through the last page so a query change does not discard accumulated rows.
        // A fresh load replaces those rows and permits client sorting again.
        listPaginated: [
            false,
            {
                listLoadData: () => false,
                listLoadNextData: () => true,
            },
        ],
        savingCustomProperties: [
            {} as Record<string, true>,
            {
                customPropertyUpdateStarted: (state, { accountId, definitionId }) => ({
                    ...state,
                    [customPropertySavingKey(accountId, definitionId)]: true,
                }),
                customPropertyUpdateFinished: (state, { accountId, definitionId }) => {
                    const next = { ...state }
                    delete next[customPropertySavingKey(accountId, definitionId)]
                    return next
                },
            },
        ],
        customPropertyOverrides: [
            {} as Record<string, CustomPropertyValueWriteApi['value']>,
            {
                setCustomPropertyOverride: (state, { accountId, definitionId, value }) => {
                    const next = { ...state }
                    const key = customPropertySavingKey(accountId, definitionId)
                    if (value === null) {
                        delete next[key]
                    } else {
                        next[key] = value
                    }
                    return next
                },
                clearCustomPropertyOverrides: () => ({}),
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
        // Keep saved assignments visible until the refetch replaces stale cells.
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
        // Keep saved tags visible until the refetch replaces stale cells.
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
        assignedToCurrentUser: [
            (s) => [s.assignedToFilter, s.currentUserId],
            (assignedToFilter: RoleFilterValue, currentUserId: number | null): boolean =>
                currentUserId !== null && assignedToFilter.length === 1 && assignedToFilter[0] === currentUserId,
        ],
        isCustomPropertySaving: [
            (s) => [s.savingCustomProperties],
            (savingCustomProperties: Record<string, true>) =>
                (accountId: string, definitionId: string): boolean =>
                    !!savingCustomProperties[customPropertySavingKey(accountId, definitionId)],
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
            (s) => [s.searchQuery, s.tagsFilter, s.assignmentStatus, s.accountFilters],
            (
                searchQuery: string,
                tagsFilter: string[],
                assignmentStatus: AssignmentStatus,
                accountFilters: AccountFilter[]
            ): number =>
                [
                    !!searchQuery.trim(),
                    tagsFilter.length > 0,
                    assignmentStatus !== 'all',
                    accountFilters.length > 0,
                ].filter(Boolean).length,
        ],
        viewState: [
            (s) => [
                s.selectColumns,
                s.searchQuery,
                s.tagsFilter,
                s.assignmentStatus,
                s.assignedToFilter,
                s.sortOrder,
                s.tileFilter,
                s.tiles,
                s.accountFilters,
                s.columnDisplay,
            ],
            (
                columns: string[],
                search: string,
                tags: string[],
                assignmentStatus: AssignmentStatus,
                assignedTo: RoleFilterValue,
                sortOrder: AccountSortOrder,
                tileFilter: TileFilter | null,
                tiles: import('./accountsOverviewTilesLogic').AccountsOverviewTile[],
                customProperties: AccountFilter[],
                columnDisplay: AccountColumnDisplayState
            ): AccountsViewState => ({
                columns,
                sortOrder,
                filters: { search, assignmentStatus, assignedTo, tags, tileFilter, customProperties },
                tiles,
                columnDisplay,
            }),
        ],
        viewUrlState: [
            (s) => [
                s.searchQuery,
                s.tagsFilter,
                s.assignmentStatus,
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
                assignmentStatus: AssignmentStatus,
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
                if (assignmentStatus === 'unassigned') {
                    state.assignmentStatus = 'unassigned'
                } else if (assignmentStatus === 'assigned') {
                    state.assignmentStatus = 'assigned'
                    if (assignedToFilter.length > 0) {
                        state.assignedTo = assignedToFilter
                    }
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
                // Without an explicit status, a nonempty hash would restore as a legacy assigned-only view.
                if (assignmentStatus === 'all' && Object.keys(state).length > 0) {
                    state.assignmentStatus = 'all'
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
                s.assignmentStatus,
                s.assignedToFilter,
                s.accountIdFilter,
                s.tileFilter,
                s.accountFilters,
                s.relationshipDefinitionsById,
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
                assignmentStatus: AssignmentStatus,
                assignedToFilter: RoleFilterValue,
                accountIdFilter: string | null,
                tileFilter: TileFilter | null,
                accountFilters: AccountFilter[],
                relationshipDefinitionsById: Record<string, AccountRelationshipDefinitionApi>,
                customPropertyDefinitionsById: Record<string, CustomPropertyDefinitionApi>,
                columnDisplay: AccountColumnDisplayState,
                sortOrder: AccountSortOrder,
                canSortClientSide: boolean
            ): BuildAccountsTableQueryPlanInput => ({
                querySelectColumns,
                visibleColumnNames,
                searchQuery,
                tagsFilter,
                assignmentStatus,
                assignedToFilter,
                accountIdFilter,
                tileFilter,
                accountFilters,
                relationshipDefinitionsById,
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
            (s) => [
                s.accountsTableQueryPlan,
                s.relationshipDefinitionsLoaded,
                s.awaitingSavedView,
                s.viewStateHydrated,
            ],
            (
                accountsTableQueryPlan: AccountsTableQueryPlan,
                relationshipDefinitionsLoaded: boolean,
                awaitingSavedView: boolean,
                viewStateHydrated: boolean
            ): AccountsTableQuery | null =>
                relationshipDefinitionsLoaded && !awaitingSavedView && viewStateHydrated
                    ? accountsTableQueryPlan.query
                    : null,
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
            (s) => [
                s.overviewMetrics,
                s.accountsTableQueryPlan,
                s.relationshipDefinitionsLoaded,
                s.awaitingSavedView,
                s.viewStateHydrated,
            ],
            (
                overviewMetrics: AccountsTableMetric[],
                accountsTableQueryPlan: AccountsTableQueryPlan,
                relationshipDefinitionsLoaded: boolean,
                awaitingSavedView: boolean,
                viewStateHydrated: boolean
            ): AccountsTableQuery | null => {
                if (
                    overviewMetrics.length === 0 ||
                    !relationshipDefinitionsLoaded ||
                    awaitingSavedView ||
                    !viewStateHydrated
                ) {
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
        applyViewState: ({ viewState, options }) => {
            cache.assignmentStateResolved = true
            if (options.source === 'draft') {
                actions.setDraftRestored(true)
            }
            cache.searchGeneration = (cache.searchGeneration ?? 0) + 1
            cache.applyingViewState = true
            try {
                if (options.columns === 'restore') {
                    actions.restoreSelectColumns(viewState.columns)
                } else if (options.columns === 'defaults') {
                    actions.resetColumns()
                }
                actions.setColumnDisplayConfig(viewState.columnDisplay)
                actions.setSearchQuery(viewState.filters.search)
                actions.setTagsFilter(viewState.filters.tags)
                actions.setAssignmentStatus(viewState.filters.assignmentStatus)
                actions.setAssignedToFilter(
                    viewState.filters.assignmentStatus === 'assigned' ? viewState.filters.assignedTo : []
                )
                actions.setAccountFilters(viewState.filters.customProperties)
                actions.setSortOrder(viewState.sortOrder)
                actions.setTiles(viewState.tiles)
                actions.setTileFilter(viewState.filters.tileFilter)
            } finally {
                cache.applyingViewState = false
            }
            // A fallback snapshot would become a draft that blocks the pending saved view.
            if (options.source !== 'defaults') {
                actions.persistViewState()
            }
        },
        persistViewState: ({ search }) => {
            const draftIdentity = getAccountsViewDraftIdentity(values.currentTeamId, values.user)
            if (
                !values.viewStateHydrated ||
                values.awaitingSavedView ||
                cache.applyingViewState ||
                !draftIdentity ||
                !objectsEqual(cache.viewStateDraftIdentity, draftIdentity) ||
                !accountsPathToWriteBackTo(values.accountIdFilter)
            ) {
                return
            }
            const viewState = {
                ...values.viewState,
                filters: { ...values.viewState.filters, search: search ?? values.searchInput },
            }
            writeAccountsViewDraft(draftIdentity.teamId, draftIdentity.userId, viewState)
        },
        setAwaitingSavedView: ({ awaiting }) => {
            if (!awaiting) {
                actions.persistViewState()
                actions.syncViewStateToUrl()
            }
        },
        setSearchQuery: () => persistViewStateAndUrl(actions, cache.applyingViewState, values.viewStateHydrated),
        setTagsFilter: () => persistViewStateAndUrl(actions, cache.applyingViewState, values.viewStateHydrated),
        setSortOrder: () => persistViewStateAndUrl(actions, cache.applyingViewState, values.viewStateHydrated),
        restoreSelectColumns: () => persistViewStateAndUrl(actions, cache.applyingViewState, values.viewStateHydrated),
        selectColumn: () => persistViewStateAndUrl(actions, cache.applyingViewState, values.viewStateHydrated),
        [accountsColumnConfigLogic.actionTypes.moveColumn]: () =>
            persistViewStateAndUrl(actions, cache.applyingViewState, values.viewStateHydrated),
        setColumnDisplay: () => persistViewStateAndUrl(actions, cache.applyingViewState, values.viewStateHydrated),
        setColumnDisplayConfig: () =>
            persistViewStateAndUrl(actions, cache.applyingViewState, values.viewStateHydrated),
        setTileFilter: () => persistViewStateAndUrl(actions, cache.applyingViewState, values.viewStateHydrated),
        setTiles: () => persistViewStateAndUrl(actions, cache.applyingViewState, values.viewStateHydrated),
        [accountsOverviewTilesLogic.actionTypes.addTile]: () =>
            persistViewStateAndUrl(actions, cache.applyingViewState, values.viewStateHydrated),
        [accountsOverviewTilesLogic.actionTypes.updateTile]: () =>
            persistViewStateAndUrl(actions, cache.applyingViewState, values.viewStateHydrated),
        [accountsOverviewTilesLogic.actionTypes.removeTile]: () =>
            persistViewStateAndUrl(actions, cache.applyingViewState, values.viewStateHydrated),
        [accountsOverviewTilesLogic.actionTypes.moveTile]: () =>
            persistViewStateAndUrl(actions, cache.applyingViewState, values.viewStateHydrated),
        [accountsOverviewTilesLogic.actionTypes.resetTiles]: () =>
            persistViewStateAndUrl(actions, cache.applyingViewState, values.viewStateHydrated),
        listLoadData: ({ queryId }) => {
            if (cache.awaitingCustomPropertyRefresh) {
                cache.awaitingCustomPropertyRefresh = false
                cache.customPropertyRefreshQueryId = queryId
            }
        },
        listLoadDataSuccess: ({ payload }) => {
            if (payload?.queryId !== cache.customPropertyRefreshQueryId) {
                return
            }
            cache.customPropertyRefreshQueryId = undefined
            actions.clearCustomPropertyOverrides()
        },
        loadCustomPropertyDefinitionsSuccess: ({ customPropertyDefinitions }) => {
            cache.customPropertyDefinitionsLoaded = true
            if (!cache.relationshipDefinitionsLoaded) {
                return
            }
            const definitionsById = Object.fromEntries(
                customPropertyDefinitions.map((definition) => [definition.id, definition])
            )
            const supportedFilters = supportedAccountFilters(
                values.accountFilters,
                definitionsById,
                values.relationshipDefinitionsById
            )
            if (!objectsEqual(supportedFilters, values.accountFilters)) {
                actions.setAccountFilters(supportedFilters)
            }
        },
        loadRelationshipDefinitionsSuccess: () => {
            cache.relationshipDefinitionsLoaded = true
            if (!cache.customPropertyDefinitionsLoaded) {
                return
            }
            const supportedFilters = supportedAccountFilters(
                values.accountFilters,
                values.customPropertyDefinitionsById,
                values.relationshipDefinitionsById
            )
            if (!objectsEqual(supportedFilters, values.accountFilters)) {
                actions.setAccountFilters(supportedFilters)
            }
        },
        loadRelationshipDefinitionsFailure: () => {
            cache.relationshipDefinitionsLoaded = true
            actions.setAccountFilters(values.accountFilters)
        },
        setAccountFilters: ({ filters }) => {
            persistViewStateAndUrl(actions, cache.applyingViewState, values.viewStateHydrated)
            if (!cache.customPropertyDefinitionsLoaded || !cache.relationshipDefinitionsLoaded) {
                return
            }
            const supportedFilters = supportedAccountFilters(
                filters,
                values.customPropertyDefinitionsById,
                values.relationshipDefinitionsById
            )
            if (!objectsEqual(supportedFilters, filters)) {
                actions.setAccountFilters(supportedFilters)
            }
        },
        updateAccountFilters: ({ filters }, _, __, previousState) => {
            const supportedFilters =
                cache.customPropertyDefinitionsLoaded && cache.relationshipDefinitionsLoaded
                    ? supportedAccountFilters(
                          filters,
                          values.customPropertyDefinitionsById,
                          values.relationshipDefinitionsById
                      )
                    : filters
            const previousFilters = selectors.accountFilters(previousState)
            const changedFilter =
                supportedFilters.find((filter, index) => !objectsEqual(filter, previousFilters[index])) ??
                previousFilters.find((filter, index) => !objectsEqual(filter, supportedFilters[index]))
            actions.setAccountFilters(supportedFilters)
            const fieldKind =
                changedFilter?.type === 'account'
                    ? 'account_field'
                    : changedFilter?.type === 'account_relationship'
                      ? 'relationship'
                      : 'custom_property'
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
            const searchGeneration = cache.searchGeneration ?? 0
            actions.persistViewState(query)
            await breakpoint(SEARCH_DEBOUNCE_MS)
            if (searchGeneration !== (cache.searchGeneration ?? 0)) {
                return
            }
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
                case 'assignment_status':
                    properties.value = values.assignmentStatus
                    properties.is_cleared = values.assignmentStatus === 'all'
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
        // Selected users apply only to assigned accounts.
        setAssignmentStatus: ({ status }) => {
            persistViewStateAndUrl(actions, cache.applyingViewState, values.viewStateHydrated)
            if (status !== 'assigned' && values.assignedToFilter.length > 0) {
                actions.setAssignedToFilter([])
            }
        },
        setAssignedToCurrentUser: ({ value }) => {
            actions.setAssignedToFilter(value && values.currentUserId !== null ? [values.currentUserId] : [])
        },
        setAssignedToFilter: ({ value }) => {
            persistViewStateAndUrl(actions, cache.applyingViewState, values.viewStateHydrated)
            if (value.length > 0 && values.assignmentStatus !== 'assigned') {
                actions.setAssignmentStatus('assigned')
            }
            // Notes uses the same My accounts preference.
            if (!cache.pendingMineOnlyRestore) {
                cache.mirroringMineOnly = true
                try {
                    actions.setMineOnly(values.assignedToCurrentUser)
                } finally {
                    cache.mirroringMineOnly = false
                }
            }
        },
        setMineOnly: ({ mineOnly }) => {
            if (cache.mirroringMineOnly) {
                return
            }
            if (!isAccountsListPath()) {
                cache.mineOnlyChangedOutsideAccounts = mineOnly
                return
            }
            if (cache.userUnavailable) {
                cache.pendingMineOnlyRestore = mineOnly
                return
            }
            if (mineOnly && values.currentUserId !== null) {
                actions.setAssignedToFilter([values.currentUserId])
            } else if (!mineOnly && values.assignedToCurrentUser) {
                actions.setAssignedToFilter([])
            }
        },
        [teamLogic.actionTypes.loadCurrentTeamSuccess]: () => {
            const draftIdentity = getAccountsViewDraftIdentity(values.currentTeamId, values.user)
            if (
                !values.viewStateHydrated ||
                (draftIdentity && !objectsEqual(cache.viewStateDraftIdentity, draftIdentity))
            ) {
                actions.restoreViewStateFromRoute()
            }
        },
        // Viewer-relative preferences and legacy mine links must wait for the user ID.
        loadUserSuccess: ({ user }) => {
            cache.userUnavailable = user === null
            const draftIdentity = getAccountsViewDraftIdentity(values.currentTeamId, values.user)
            if (
                !values.viewStateHydrated ||
                (draftIdentity && !objectsEqual(cache.viewStateDraftIdentity, draftIdentity))
            ) {
                actions.restoreViewStateFromRoute()
                return
            }
            if (cache.pendingMineOnlyRestore && values.currentUserId !== null) {
                cache.pendingMineOnlyRestore = false
                actions.setAssignedToFilter([values.currentUserId])
                return
            }
            if (
                !cache.assignmentStateResolved &&
                values.mineOnly &&
                values.currentUserId !== null &&
                !values.assignedToFilter.length &&
                values.assignmentStatus !== 'unassigned'
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
            persistViewStateAndUrl(actions, cache.applyingViewState, values.viewStateHydrated)
            clearSortIfColumnRemoved(values, actions)
        },
        unselectColumn: () => {
            persistViewStateAndUrl(actions, cache.applyingViewState, values.viewStateHydrated)
            clearSortIfColumnRemoved(values, actions)
        },
        resetColumns: () => {
            persistViewStateAndUrl(actions, cache.applyingViewState, values.viewStateHydrated)
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
        restoreViewStateFromRoute: ({ method }) => {
            const pathname = removeProjectIdIfPresent(router.values.location.pathname)
            const sharedView = hasSharedView(router.values.hashParams)
                ? (router.values.hashParams.view as AccountsViewUrlState)
                : null
            const pendingUrlRestore = cache.pendingUrlRestore
            cache.pendingUrlRestore = undefined
            if (
                method === 'REPLACE' &&
                pendingUrlRestore &&
                pendingUrlRestore.pathname === pathname &&
                objectsEqual(pendingUrlRestore.view, sharedView ?? {})
            ) {
                return
            }

            const draftIdentity = getAccountsViewDraftIdentity(values.currentTeamId, values.user)
            if (!sharedView && !draftIdentity) {
                actions.setViewStateHydrated(false)
                return
            }

            const previousDraftIdentity = cache.viewStateDraftIdentity
            cache.assignmentStateResolved = false
            cache.pendingMineOnlyRestore = false
            cache.viewStateDraftIdentity = draftIdentity
            actions.setDraftRestored(false)
            let restored = false
            const draft = draftIdentity ? readAccountsViewDraft(draftIdentity.teamId, draftIdentity.userId) : null
            if (sharedView) {
                cache.mineOnlyChangedOutsideAccounts = undefined
                cache.pendingMineOnlyRestore = !!sharedView.mine && values.currentUserId === null
                actions.applyViewState(
                    accountsViewStateFromUrl(
                        sharedView,
                        values.defaultSelectColumns,
                        values.currentUserId,
                        draft?.tiles ?? values.tiles
                    ),
                    { source: 'shared_url', columns: Array.isArray(sharedView.columns) ? 'restore' : 'defaults' }
                )
                restored = true
            } else if (isAccountsListPath() || pathname.startsWith(`${urls.customerAnalyticsAccounts()}/`)) {
                const mineOnly = cache.mineOnlyChangedOutsideAccounts
                cache.mineOnlyChangedOutsideAccounts = undefined
                if (mineOnly !== undefined) {
                    cache.pendingMineOnlyRestore = mineOnly && values.currentUserId === null
                    actions.applyViewState(
                        viewStateWithMineOnly(draft ?? values.viewState, mineOnly, values.currentUserId),
                        {
                            source: draft ? 'draft' : 'defaults',
                            columns: draft ? 'restore' : 'keep',
                        }
                    )
                    restored = true
                } else if (draft) {
                    actions.applyViewState(draft, { source: 'draft', columns: 'restore' })
                    restored = true
                } else if (previousDraftIdentity && !objectsEqual(previousDraftIdentity, draftIdentity)) {
                    actions.applyViewState(
                        viewStateWithMineOnly(
                            accountsViewStateFromUrl(
                                {},
                                values.defaultSelectColumns,
                                values.currentUserId,
                                DEFAULT_TILES
                            ),
                            values.mineOnly,
                            values.currentUserId
                        ),
                        { source: 'defaults', columns: 'defaults' }
                    )
                } else if (values.mineOnly) {
                    if (values.currentUserId === null) {
                        cache.pendingMineOnlyRestore = true
                    } else {
                        actions.applyViewState(viewStateWithMineOnly(values.viewState, true, values.currentUserId), {
                            source: 'defaults',
                            columns: 'keep',
                        })
                    }
                }
            }
            actions.setViewStateHydrated(true)
            if (restored) {
                actions.persistViewState()
            }
        },
        updateAccountCustomProperty: async ({ accountId, definition, value }) => {
            if (
                definition.is_canonical ||
                definition.source ||
                values.isCustomPropertySaving(accountId, definition.id)
            ) {
                return
            }
            const key = customPropertySavingKey(accountId, definition.id)
            const previous = values.customPropertyOverrides[key] ?? null
            actions.customPropertyUpdateStarted(accountId, definition.id)
            actions.setCustomPropertyOverride(accountId, definition.id, value)
            try {
                await accountsCustomPropertyValuesCreate(String(values.currentTeamId), accountId, {
                    definition: definition.id,
                    value,
                })
                posthog.capture(AccountsEvents.CustomPropertyUpdated, {
                    display_type: definition.display_type,
                    workflow_reference: definition.has_workflow_reference,
                })
                cache.awaitingCustomPropertyRefresh = true
                dataNodeLogic.findMounted({ key: ACCOUNTS_TABLE_DATA_NODE_KEY })?.actions.loadData('force_async')
                dataNodeLogic.findMounted({ key: ACCOUNTS_METRICS_DATA_NODE_KEY })?.actions.loadData('force_async')
            } catch (error) {
                actions.setCustomPropertyOverride(accountId, definition.id, previous)
                posthog.captureException(error as Error, { scope: 'accountsLogic.updateAccountCustomProperty' })
                lemonToast.error('Failed to update custom property')
            } finally {
                actions.customPropertyUpdateFinished(accountId, definition.id)
            }
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
            // Reflect edits before the debounce so the controlled tag input does not revert.
            actions.setTagsOverride(accountId, tags)
            // This breakpoint is shared across accounts. A second account edit cancels the first pending save.
            await breakpoint(TAGS_SAVE_DEBOUNCE_MS)
            actions.tagsUpdateStarted(accountId)
            try {
                await accountsPartialUpdate(String(values.currentTeamId), accountId, { tags })
                posthog.capture(AccountsEvents.TagsUpdated, { tag_count: tags.length })
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
            // Remove excluding filters so the requested account can render.
            if (!isVisible) {
                if (values.tagsFilter.length > 0) {
                    actions.setTagsFilter([])
                }
                if (values.assignmentStatus !== 'all') {
                    actions.setAssignmentStatus('all')
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
            // Cancel earlier scrolls and do not repeat a completed scroll when the browser tab resumes.
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
        // Relationship cells need member names before an editor opens.
        actions.ensureAllMembersLoaded()
        actions.restoreViewStateFromRoute()
    }),
    actionToUrl(({ values, cache }) => ({
        syncViewStateToUrl: () => {
            if (!values.viewStateHydrated || values.awaitingSavedView) {
                return undefined
            }
            const pathname = accountsPathToWriteBackTo(values.accountIdFilter)
            if (!pathname) {
                return undefined
            }
            const view = objectsEqual(values.viewUrlState, {}) ? {} : values.viewUrlState
            const currentView = hasSharedView(router.values.hashParams)
                ? (router.values.hashParams.view as AccountsViewUrlState)
                : {}
            if (objectsEqual(currentView, view)) {
                return undefined
            }
            const pendingUrlRestore = {
                pathname: removeProjectIdIfPresent(pathname),
                view,
            }
            cache.pendingUrlRestore = pendingUrlRestore
            queueMicrotask(() => {
                if (cache.pendingUrlRestore === pendingUrlRestore) {
                    cache.pendingUrlRestore = undefined
                }
            })
            return [pathname, router.values.searchParams, objectsEqual(view, {}) ? {} : { view }, { replace: true }]
        },
    })),
    urlToAction(({ actions, values }) => {
        const openAccountByPath = (accountId: string | undefined, rawTab?: string): void => {
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
            [urls.customerAnalyticsAccounts()]: (_, __, ___, { method }): void => {
                actions.restoreViewStateFromRoute(method)
                if (values.accountIdFilter !== null) {
                    actions.setAccountIdFilter(null)
                }
            },
            // Keep the list draft while the account ID controls the detail query.
            [urls.customerAnalyticsAccount(':accountId')]: ({ accountId }, __, ___, { method }): void => {
                actions.restoreViewStateFromRoute(method)
                openAccountByPath(accountId)
            },
            [urls.customerAnalyticsAccount(':accountId', ':tab')]: ({ accountId, tab }, __, ___, { method }): void => {
                actions.restoreViewStateFromRoute(method)
                openAccountByPath(accountId, tab)
            },
        }
    }),
])
