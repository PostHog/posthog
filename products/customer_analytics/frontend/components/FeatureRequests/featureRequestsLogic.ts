import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { uuid } from 'lib/utils/dom'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { TeamPublicType, TeamType } from '../../../../../frontend/src/types'
import {
    accountsList,
    featureRequestProductAreasCreate,
    featureRequestProductAreasList,
    featureRequestProductAreasPartialUpdate,
    featureRequestsArchiveCreate,
    featureRequestsCreate,
    featureRequestsHistoryList,
    featureRequestsList,
    featureRequestsRestoreCreate,
    featureRequestsRetrieve,
    featureRequestsUpdate,
} from '../../generated/api'
import type {
    AccountApi,
    FeatureRequestApi,
    FeatureRequestHistoryApi,
    FeatureRequestProductAreaApi,
    FeatureRequestStatusEnumApi,
    PaginatedFeatureRequestListApi,
    RequestPriorityEnumApi,
} from '../../generated/api.schemas'
import {
    FEATURE_REQUEST_ORDERING_OPTIONS,
    FEATURE_REQUEST_PRIORITY_FILTER_OPTIONS,
    FEATURE_REQUEST_STATUS_OPTIONS,
    FeatureRequestArchiveState,
    FeatureRequestOrdering,
    FeatureRequestPriorityFilter,
} from './featureRequestOptions'

export const FEATURE_REQUESTS_PAGE_SIZE = 20

const FILTER_URL_KEYS = ['search', 'status', 'priority', 'product_area', 'account', 'archive', 'sort', 'page'] as const
const VALID_STATUSES = new Set(FEATURE_REQUEST_STATUS_OPTIONS.map((option) => option.value))
const VALID_PRIORITIES = new Set(FEATURE_REQUEST_PRIORITY_FILTER_OPTIONS.map((option) => option.value))
const VALID_ORDERINGS = new Set(FEATURE_REQUEST_ORDERING_OPTIONS.map((option) => option.value))
const VALID_ARCHIVE_STATES = new Set<FeatureRequestArchiveState>(['active', 'archived', 'all'])

export interface FeatureRequestListState {
    searchQuery: string
    statusFilter: FeatureRequestStatusEnumApi[]
    priorityFilter: FeatureRequestPriorityFilter[]
    productAreaFilter: string[]
    accountFilter: string[]
    archiveState: FeatureRequestArchiveState
    requestOrdering: FeatureRequestOrdering
    featureRequestsPage: number
}

function parseListParam(raw: unknown, valid?: Set<string>): string[] {
    if (typeof raw !== 'string' || !raw) {
        return []
    }
    return raw
        .split(',')
        .map((value) => value.trim())
        .filter((value) => value && (!valid || valid.has(value)))
}

export function parseFeatureRequestSearchParams(searchParams: Record<string, any>): FeatureRequestListState {
    const archiveState =
        typeof searchParams.archive === 'string' &&
        VALID_ARCHIVE_STATES.has(searchParams.archive as FeatureRequestArchiveState)
            ? (searchParams.archive as FeatureRequestArchiveState)
            : 'active'
    const requestOrdering =
        typeof searchParams.sort === 'string' && VALID_ORDERINGS.has(searchParams.sort as FeatureRequestOrdering)
            ? (searchParams.sort as FeatureRequestOrdering)
            : '-updated_at'
    const parsedPage = Number(searchParams.page)
    return {
        searchQuery: typeof searchParams.search === 'string' ? searchParams.search : '',
        statusFilter: parseListParam(searchParams.status, VALID_STATUSES) as FeatureRequestStatusEnumApi[],
        priorityFilter: parseListParam(searchParams.priority, VALID_PRIORITIES) as FeatureRequestPriorityFilter[],
        productAreaFilter: parseListParam(searchParams.product_area),
        accountFilter: parseListParam(searchParams.account),
        archiveState,
        requestOrdering,
        featureRequestsPage: Number.isInteger(parsedPage) && parsedPage > 0 ? parsedPage : 1,
    }
}

export function featureRequestSearchParams(values: FeatureRequestListState): Record<string, string> {
    const params: Record<string, string> = {}
    if (values.searchQuery.trim()) {
        params.search = values.searchQuery
    }
    if (values.statusFilter.length) {
        params.status = values.statusFilter.join(',')
    }
    if (values.priorityFilter.length) {
        params.priority = values.priorityFilter.join(',')
    }
    if (values.productAreaFilter.length) {
        params.product_area = values.productAreaFilter.join(',')
    }
    if (values.accountFilter.length) {
        params.account = values.accountFilter.join(',')
    }
    if (values.archiveState !== 'active') {
        params.archive = values.archiveState
    }
    if (values.requestOrdering !== '-updated_at') {
        params.sort = values.requestOrdering
    }
    if (values.featureRequestsPage > 1) {
        params.page = String(values.featureRequestsPage)
    }
    return params
}

function currentUrlWithFilters(
    values: FeatureRequestListState
): [string, Record<string, any>, any, { replace: boolean }] {
    const searchParams = { ...router.values.searchParams }
    for (const key of FILTER_URL_KEYS) {
        delete searchParams[key]
    }
    Object.assign(searchParams, featureRequestSearchParams(values))
    return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
}

function toggleValue<T extends string>(values: T[], value: T): T[] {
    return values.includes(value) ? values.filter((item) => item !== value) : [...values, value]
}

const newIdempotencyKey = (): string => uuid()

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface featureRequestsLogicValues {
    currentTeam: TeamPublicType | TeamType | null // teamLogic
    accountFilter: string[]
    accountId: string | null
    accountOptions: {
        key: string
        label: string
    }[]
    accountSearch: string
    accounts: AccountApi[]
    accountsError: string | null
    accountsLoading: boolean
    activeProductAreas: FeatureRequestProductAreaApi[]
    activeRequest: FeatureRequestApi | null
    activeRequestError: string | null
    activeRequestId: string | null
    activeRequestLoading: boolean
    archiveState: FeatureRequestArchiveState
    createRequestOpen: boolean
    currentTeamId: string
    description: string
    editAccountId: string | null
    editDescription: string
    editDisabledReason: string | undefined
    editError: string | null
    editExpectedVersion: number
    editIsStale: boolean
    editPriority: RequestPriorityEnumApi | null
    editProductAreaIds: string[]
    editProductAreaOptions: {
        disabledReason?: string
        key: string
        label: string
    }[]
    editRequestOpen: boolean
    editStatus: FeatureRequestStatusEnumApi
    editTitle: string
    editingProductAreaId: string | null
    featureRequestsError: string | null
    featureRequestsPage: number
    featureRequestsResponse: PaginatedFeatureRequestListApi
    featureRequestsResponseLoading: boolean
    hasActiveFilters: boolean
    idempotencyKey: string
    listSearchParams: Record<string, string>
    mutatingArchive: boolean
    priorityFilter: FeatureRequestPriorityFilter[]
    productAreaActive: boolean
    productAreaDisplayOrder: number
    productAreaFilter: string[]
    productAreaIds: string[]
    productAreaName: string
    productAreaOptions: {
        key: string
        label: string
    }[]
    productAreaSaveDisabledReason: string | undefined
    productAreas: FeatureRequestProductAreaApi[]
    productAreasError: string | null
    productAreasLoading: boolean
    productAreasOpen: boolean
    requestHistory: FeatureRequestHistoryApi[]
    requestHistoryError: string | null
    requestHistoryLoading: boolean
    requestHistoryShowingAll: boolean
    requestOrdering: FeatureRequestOrdering
    savingProductArea: boolean
    savingRequestChanges: boolean
    searchQuery: string
    statusFilter: FeatureRequestStatusEnumApi[]
    submitDisabledReason: string | undefined
    submittingRequest: boolean
    title: string
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface featureRequestsLogicActions {
    archiveActiveRequest: () => {
        value: true
    }
    clearFilters: () => {
        value: true
    }
    closeCreateRequest: () => {
        value: true
    }
    closeEditRequest: () => {
        value: true
    }
    closeProductAreas: () => {
        value: true
    }
    loadAccounts: (search?: string) => string
    loadAccountsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadAccountsSuccess: (
        accounts: AccountApi[],
        payload?: string
    ) => {
        accounts: AccountApi[]
        payload?: string
    }
    loadActiveRequest: (requestId: string) => string
    loadActiveRequestFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadActiveRequestSuccess: (
        activeRequest: FeatureRequestApi,
        payload?: string
    ) => {
        activeRequest: FeatureRequestApi
        payload?: string
    }
    loadFeatureRequests: () => any
    loadFeatureRequestsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadFeatureRequestsSuccess: (
        featureRequestsResponse: PaginatedFeatureRequestListApi,
        payload?: any
    ) => {
        featureRequestsResponse: PaginatedFeatureRequestListApi
        payload?: any
    }
    loadProductAreas: () => any
    loadProductAreasFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadProductAreasSuccess: (
        productAreas: FeatureRequestProductAreaApi[],
        payload?: any
    ) => {
        productAreas: FeatureRequestProductAreaApi[]
        payload?: any
    }
    loadRequestHistory: (requestId: string) => string
    loadRequestHistoryFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadRequestHistorySuccess: (
        requestHistory: FeatureRequestHistoryApi[],
        payload?: string
    ) => {
        requestHistory: FeatureRequestHistoryApi[]
        payload?: string
    }
    openCreateRequest: () => {
        value: true
    }
    openEditRequest: (featureRequest: FeatureRequestApi) => {
        featureRequest: FeatureRequestApi
    }
    openProductAreas: () => {
        value: true
    }
    reloadLatestForEdit: () => {
        value: true
    }
    restoreActiveRequest: () => {
        value: true
    }
    saveProductArea: () => {
        value: true
    }
    saveRequestChanges: () => {
        value: true
    }
    setAccountId: (accountId: string | null) => {
        accountId: string | null
    }
    setAccountSearch: (accountSearch: string) => {
        accountSearch: string
    }
    setActiveRequestId: (requestId: string | null) => {
        requestId: string | null
    }
    setArchiveState: (archiveState: FeatureRequestArchiveState) => {
        archiveState: FeatureRequestArchiveState
    }
    setDescription: (description: string) => {
        description: string
    }
    setEditAccountId: (editAccountId: string | null) => {
        editAccountId: string | null
    }
    setEditDescription: (editDescription: string) => {
        editDescription: string
    }
    setEditError: (editError: string | null) => {
        editError: string | null
    }
    setEditExpectedVersion: (editExpectedVersion: number) => {
        editExpectedVersion: number
    }
    setEditIsStale: (editIsStale: boolean) => {
        editIsStale: boolean
    }
    setEditPriority: (editPriority: RequestPriorityEnumApi | null) => {
        editPriority: RequestPriorityEnumApi | null
    }
    setEditProductAreaIds: (editProductAreaIds: string[]) => {
        editProductAreaIds: string[]
    }
    setEditStatus: (editStatus: FeatureRequestStatusEnumApi) => {
        editStatus: FeatureRequestStatusEnumApi
    }
    setEditTitle: (editTitle: string) => {
        editTitle: string
    }
    setFeatureRequestsPage: (page: number) => {
        page: number
    }
    setFiltersFromUrl: (filters: FeatureRequestListState) => {
        filters: FeatureRequestListState
    }
    setIdempotencyKey: (idempotencyKey: string) => {
        idempotencyKey: string
    }
    setMutatingArchive: (mutatingArchive: boolean) => {
        mutatingArchive: boolean
    }
    setProductAreaActive: (productAreaActive: boolean) => {
        productAreaActive: boolean
    }
    setProductAreaDisplayOrder: (productAreaDisplayOrder: number) => {
        productAreaDisplayOrder: number
    }
    setProductAreaIds: (productAreaIds: string[]) => {
        productAreaIds: string[]
    }
    setProductAreaName: (productAreaName: string) => {
        productAreaName: string
    }
    setRequestHistoryShowingAll: (showingAll: boolean) => {
        showingAll: boolean
    }
    setRequestOrdering: (requestOrdering: FeatureRequestOrdering) => {
        requestOrdering: FeatureRequestOrdering
    }
    setSavingProductArea: (savingProductArea: boolean) => {
        savingProductArea: boolean
    }
    setSavingRequestChanges: (savingRequestChanges: boolean) => {
        savingRequestChanges: boolean
    }
    setSearchQuery: (searchQuery: string) => {
        searchQuery: string
    }
    setSubmittingRequest: (submittingRequest: boolean) => {
        submittingRequest: boolean
    }
    setTitle: (title: string) => {
        title: string
    }
    startEditingProductArea: (productArea: FeatureRequestProductAreaApi) => {
        productArea: FeatureRequestProductAreaApi
    }
    startNewProductArea: () => {
        value: true
    }
    submitRequest: () => {
        value: true
    }
    toggleAccountFilter: (accountId: string) => {
        accountId: string
    }
    togglePriorityFilter: (requestPriority: FeatureRequestPriorityFilter) => {
        requestPriority: FeatureRequestPriorityFilter
    }
    toggleProductAreaFilter: (productAreaId: string) => {
        productAreaId: string
    }
    toggleStatusFilter: (requestStatus: FeatureRequestStatusEnumApi) => {
        requestStatus: FeatureRequestStatusEnumApi
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface featureRequestsLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        currentTeamId: (currentTeam: TeamPublicType | TeamType | null) => string
        activeProductAreas: (productAreas: FeatureRequestProductAreaApi[]) => FeatureRequestProductAreaApi[]
        accountOptions: (accounts: AccountApi[]) => {
            key: string
            label: string
        }[]
        productAreaOptions: (activeProductAreas: FeatureRequestProductAreaApi[]) => {
            key: string
            label: string
        }[]
        editProductAreaOptions: (
            productAreas: FeatureRequestProductAreaApi[],
            editProductAreaIds: string[]
        ) => {
            disabledReason?: string
            key: string
            label: string
        }[]
        submitDisabledReason: (
            title: string,
            description: string,
            accountId: string | null,
            productAreaIds: string[],
            submittingRequest: boolean
        ) => string | undefined
        editDisabledReason: (
            editTitle: string,
            editDescription: string,
            editAccountId: string | null,
            editProductAreaIds: string[],
            savingRequestChanges: boolean
        ) => string | undefined
        productAreaSaveDisabledReason: (productAreaName: string, savingProductArea: boolean) => string | undefined
        hasActiveFilters: (
            searchQuery: string,
            statusFilter: FeatureRequestStatusEnumApi[],
            priorityFilter: FeatureRequestPriorityFilter[],
            productAreaFilter: string[],
            accountFilter: string[],
            archiveState: FeatureRequestArchiveState
        ) => boolean
        listSearchParams: (
            searchQuery: string,
            statusFilter: FeatureRequestStatusEnumApi[],
            priorityFilter: FeatureRequestPriorityFilter[],
            productAreaFilter: string[],
            accountFilter: string[],
            archiveState: FeatureRequestArchiveState,
            requestOrdering: FeatureRequestOrdering,
            featureRequestsPage: number
        ) => Record<string, string>
    }
}

export type featureRequestsLogicType = MakeLogicType<
    featureRequestsLogicValues,
    featureRequestsLogicActions,
    Record<string, any>,
    featureRequestsLogicMeta
>

export const featureRequestsLogic = kea<featureRequestsLogicType>([
    path(['products', 'customer_analytics', 'frontend', 'components', 'FeatureRequests', 'featureRequestsLogic']),
    connect(() => ({ values: [teamLogic, ['currentTeam']] })),
    actions({
        setActiveRequestId: (requestId: string | null) => ({ requestId }),
        setFeatureRequestsPage: (page: number) => ({ page }),
        setFiltersFromUrl: (filters: FeatureRequestListState) => ({ filters }),
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        toggleStatusFilter: (requestStatus: FeatureRequestStatusEnumApi) => ({ requestStatus }),
        togglePriorityFilter: (requestPriority: FeatureRequestPriorityFilter) => ({ requestPriority }),
        toggleProductAreaFilter: (productAreaId: string) => ({ productAreaId }),
        toggleAccountFilter: (accountId: string) => ({ accountId }),
        setArchiveState: (archiveState: FeatureRequestArchiveState) => ({ archiveState }),
        setRequestOrdering: (requestOrdering: FeatureRequestOrdering) => ({ requestOrdering }),
        clearFilters: true,
        openCreateRequest: true,
        closeCreateRequest: true,
        setTitle: (title: string) => ({ title }),
        setDescription: (description: string) => ({ description }),
        setAccountId: (accountId: string | null) => ({ accountId }),
        setAccountSearch: (accountSearch: string) => ({ accountSearch }),
        setProductAreaIds: (productAreaIds: string[]) => ({ productAreaIds }),
        setIdempotencyKey: (idempotencyKey: string) => ({ idempotencyKey }),
        submitRequest: true,
        setSubmittingRequest: (submittingRequest: boolean) => ({ submittingRequest }),
        openProductAreas: true,
        closeProductAreas: true,
        startNewProductArea: true,
        startEditingProductArea: (productArea: FeatureRequestProductAreaApi) => ({ productArea }),
        setProductAreaName: (productAreaName: string) => ({ productAreaName }),
        setProductAreaDisplayOrder: (productAreaDisplayOrder: number) => ({ productAreaDisplayOrder }),
        setProductAreaActive: (productAreaActive: boolean) => ({ productAreaActive }),
        saveProductArea: true,
        setSavingProductArea: (savingProductArea: boolean) => ({ savingProductArea }),
        openEditRequest: (featureRequest: FeatureRequestApi) => ({ featureRequest }),
        closeEditRequest: true,
        setEditTitle: (editTitle: string) => ({ editTitle }),
        setEditDescription: (editDescription: string) => ({ editDescription }),
        setEditAccountId: (editAccountId: string | null) => ({ editAccountId }),
        setEditProductAreaIds: (editProductAreaIds: string[]) => ({ editProductAreaIds }),
        setEditStatus: (editStatus: FeatureRequestStatusEnumApi) => ({ editStatus }),
        setEditPriority: (editPriority: RequestPriorityEnumApi | null) => ({ editPriority }),
        setEditExpectedVersion: (editExpectedVersion: number) => ({ editExpectedVersion }),
        setEditError: (editError: string | null) => ({ editError }),
        setEditIsStale: (editIsStale: boolean) => ({ editIsStale }),
        saveRequestChanges: true,
        setSavingRequestChanges: (savingRequestChanges: boolean) => ({ savingRequestChanges }),
        reloadLatestForEdit: true,
        archiveActiveRequest: true,
        restoreActiveRequest: true,
        setMutatingArchive: (mutatingArchive: boolean) => ({ mutatingArchive }),
        setRequestHistoryShowingAll: (showingAll: boolean) => ({ showingAll }),
    }),
    loaders(({ values }) => ({
        featureRequestsResponse: [
            { count: 0, next: null, previous: null, results: [] } as PaginatedFeatureRequestListApi,
            {
                loadFeatureRequests: async () =>
                    featureRequestsList(String(values.currentTeam?.id), {
                        limit: FEATURE_REQUESTS_PAGE_SIZE,
                        offset: (values.featureRequestsPage - 1) * FEATURE_REQUESTS_PAGE_SIZE,
                        search: values.searchQuery.trim() || undefined,
                        statuses: values.statusFilter.length ? values.statusFilter : undefined,
                        priorities: values.priorityFilter.length ? values.priorityFilter : undefined,
                        product_area_ids: values.productAreaFilter.length ? values.productAreaFilter : undefined,
                        account_ids: values.accountFilter.length ? values.accountFilter : undefined,
                        archive_state: values.archiveState,
                        request_ordering: values.requestOrdering,
                    }),
            },
        ],
        activeRequest: [
            null as FeatureRequestApi | null,
            {
                loadActiveRequest: async (requestId: string) =>
                    featureRequestsRetrieve(String(values.currentTeam?.id), requestId),
            },
        ],
        requestHistory: [
            [] as FeatureRequestHistoryApi[],
            {
                loadRequestHistory: async (requestId: string) =>
                    featureRequestsHistoryList(String(values.currentTeam?.id), requestId),
            },
        ],
        accounts: [
            [] as AccountApi[],
            {
                loadAccounts: async (search: string = '') => {
                    const response = await accountsList(String(values.currentTeam?.id), {
                        limit: 100,
                        ordering: 'name',
                        search: search.trim() || undefined,
                    })
                    return response.results
                },
            },
        ],
        productAreas: [
            [] as FeatureRequestProductAreaApi[],
            {
                loadProductAreas: async () =>
                    featureRequestProductAreasList(String(values.currentTeam?.id), { include_inactive: true }),
            },
        ],
    })),
    reducers({
        activeRequestId: [null as string | null, { setActiveRequestId: (_, { requestId }) => requestId }],
        featureRequestsPage: [
            1,
            {
                setFeatureRequestsPage: (_, { page }) => page,
                setFiltersFromUrl: (_, { filters }) => filters.featureRequestsPage,
                setSearchQuery: () => 1,
                toggleStatusFilter: () => 1,
                togglePriorityFilter: () => 1,
                toggleProductAreaFilter: () => 1,
                toggleAccountFilter: () => 1,
                setArchiveState: () => 1,
                setRequestOrdering: () => 1,
                clearFilters: () => 1,
            },
        ],
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { searchQuery }) => searchQuery,
                setFiltersFromUrl: (_, { filters }) => filters.searchQuery,
                clearFilters: () => '',
            },
        ],
        statusFilter: [
            [] as FeatureRequestStatusEnumApi[],
            {
                toggleStatusFilter: (state, { requestStatus }) => toggleValue(state, requestStatus),
                setFiltersFromUrl: (_, { filters }) => filters.statusFilter,
                clearFilters: () => [],
            },
        ],
        priorityFilter: [
            [] as FeatureRequestPriorityFilter[],
            {
                togglePriorityFilter: (state, { requestPriority }) => toggleValue(state, requestPriority),
                setFiltersFromUrl: (_, { filters }) => filters.priorityFilter,
                clearFilters: () => [],
            },
        ],
        productAreaFilter: [
            [] as string[],
            {
                toggleProductAreaFilter: (state, { productAreaId }) => toggleValue(state, productAreaId),
                setFiltersFromUrl: (_, { filters }) => filters.productAreaFilter,
                clearFilters: () => [],
            },
        ],
        accountFilter: [
            [] as string[],
            {
                toggleAccountFilter: (state, { accountId }) => toggleValue(state, accountId),
                setFiltersFromUrl: (_, { filters }) => filters.accountFilter,
                clearFilters: () => [],
            },
        ],
        archiveState: [
            'active' as FeatureRequestArchiveState,
            {
                setArchiveState: (_, { archiveState }) => archiveState,
                setFiltersFromUrl: (_, { filters }) => filters.archiveState,
                clearFilters: () => 'active',
            },
        ],
        requestOrdering: [
            '-updated_at' as FeatureRequestOrdering,
            {
                setRequestOrdering: (_, { requestOrdering }) => requestOrdering,
                setFiltersFromUrl: (_, { filters }) => filters.requestOrdering,
                clearFilters: () => '-updated_at',
            },
        ],
        accountSearch: ['', { setAccountSearch: (_, { accountSearch }) => accountSearch }],
        accountsError: [
            null as string | null,
            {
                loadAccounts: () => null,
                loadAccountsSuccess: () => null,
                loadAccountsFailure: () => "Couldn't load accounts.",
            },
        ],
        featureRequestsError: [
            null as string | null,
            {
                loadFeatureRequests: () => null,
                loadFeatureRequestsSuccess: () => null,
                loadFeatureRequestsFailure: () => "Couldn't load feature requests.",
            },
        ],
        activeRequestError: [
            null as string | null,
            {
                loadActiveRequest: () => null,
                loadActiveRequestSuccess: () => null,
                loadActiveRequestFailure: () => "Couldn't load this feature request.",
                setActiveRequestId: () => null,
            },
        ],
        requestHistoryError: [
            null as string | null,
            {
                loadRequestHistory: () => null,
                loadRequestHistorySuccess: () => null,
                loadRequestHistoryFailure: () => "Couldn't load request history.",
                setActiveRequestId: () => null,
            },
        ],
        requestHistoryShowingAll: [
            false,
            {
                setRequestHistoryShowingAll: (_, { showingAll }) => showingAll,
                loadRequestHistory: () => false,
                setActiveRequestId: () => false,
            },
        ],
        productAreasError: [
            null as string | null,
            {
                loadProductAreas: () => null,
                loadProductAreasSuccess: () => null,
                loadProductAreasFailure: () => "Couldn't load product areas.",
            },
        ],
        createRequestOpen: [false, { openCreateRequest: () => true, closeCreateRequest: () => false }],
        title: ['', { setTitle: (_, { title }) => title, closeCreateRequest: () => '' }],
        description: ['', { setDescription: (_, { description }) => description, closeCreateRequest: () => '' }],
        accountId: [
            null as string | null,
            { setAccountId: (_, { accountId }) => accountId, closeCreateRequest: () => null },
        ],
        productAreaIds: [
            [] as string[],
            { setProductAreaIds: (_, { productAreaIds }) => productAreaIds, closeCreateRequest: () => [] },
        ],
        idempotencyKey: [newIdempotencyKey(), { setIdempotencyKey: (_, { idempotencyKey }) => idempotencyKey }],
        submittingRequest: [false, { setSubmittingRequest: (_, { submittingRequest }) => submittingRequest }],
        productAreasOpen: [false, { openProductAreas: () => true, closeProductAreas: () => false }],
        editingProductAreaId: [
            null as string | null,
            {
                startNewProductArea: () => null,
                startEditingProductArea: (_, { productArea }) => productArea.id,
                closeProductAreas: () => null,
            },
        ],
        productAreaName: [
            '',
            {
                startNewProductArea: () => '',
                startEditingProductArea: (_, { productArea }) => productArea.name,
                setProductAreaName: (_, { productAreaName }) => productAreaName,
            },
        ],
        productAreaDisplayOrder: [
            0,
            {
                startNewProductArea: () => 0,
                startEditingProductArea: (_, { productArea }) => productArea.display_order ?? 0,
                setProductAreaDisplayOrder: (_, { productAreaDisplayOrder }) => productAreaDisplayOrder,
            },
        ],
        productAreaActive: [
            true,
            {
                startNewProductArea: () => true,
                startEditingProductArea: (_, { productArea }) => productArea.is_active ?? true,
                setProductAreaActive: (_, { productAreaActive }) => productAreaActive,
            },
        ],
        savingProductArea: [false, { setSavingProductArea: (_, { savingProductArea }) => savingProductArea }],
        editRequestOpen: [false, { openEditRequest: () => true, closeEditRequest: () => false }],
        editTitle: [
            '',
            {
                openEditRequest: (_, { featureRequest }) => featureRequest.title,
                setEditTitle: (_, { editTitle }) => editTitle,
            },
        ],
        editDescription: [
            '',
            {
                openEditRequest: (_, { featureRequest }) => featureRequest.description,
                setEditDescription: (_, { editDescription }) => editDescription,
            },
        ],
        editAccountId: [
            null as string | null,
            {
                openEditRequest: (_, { featureRequest }) => featureRequest.account.id,
                setEditAccountId: (_, { editAccountId }) => editAccountId,
            },
        ],
        editProductAreaIds: [
            [] as string[],
            {
                openEditRequest: (_, { featureRequest }) => featureRequest.product_areas.map((area) => area.id),
                setEditProductAreaIds: (_, { editProductAreaIds }) => editProductAreaIds,
            },
        ],
        editStatus: [
            'requested' as FeatureRequestStatusEnumApi,
            {
                openEditRequest: (_, { featureRequest }) => featureRequest.request_status,
                setEditStatus: (_, { editStatus }) => editStatus,
            },
        ],
        editPriority: [
            null as RequestPriorityEnumApi | null,
            {
                openEditRequest: (_, { featureRequest }) => featureRequest.request_priority,
                setEditPriority: (_, { editPriority }) => editPriority,
            },
        ],
        editExpectedVersion: [
            1,
            {
                openEditRequest: (_, { featureRequest }) => featureRequest.version,
                setEditExpectedVersion: (_, { editExpectedVersion }) => editExpectedVersion,
            },
        ],
        editError: [
            null as string | null,
            {
                openEditRequest: () => null,
                closeEditRequest: () => null,
                setEditError: (_, { editError }) => editError,
            },
        ],
        editIsStale: [
            false,
            {
                openEditRequest: () => false,
                closeEditRequest: () => false,
                setEditIsStale: (_, { editIsStale }) => editIsStale,
            },
        ],
        savingRequestChanges: [
            false,
            { setSavingRequestChanges: (_, { savingRequestChanges }) => savingRequestChanges },
        ],
        mutatingArchive: [false, { setMutatingArchive: (_, { mutatingArchive }) => mutatingArchive }],
    }),
    selectors({
        currentTeamId: [
            (selectors) => [selectors.currentTeam],
            (currentTeam: TeamPublicType | TeamType | null): string => String(currentTeam?.id ?? ''),
        ],
        activeProductAreas: [
            (selectors) => [selectors.productAreas],
            (productAreas: FeatureRequestProductAreaApi[]): FeatureRequestProductAreaApi[] =>
                productAreas.filter((area) => area.is_active),
        ],
        accountOptions: [
            (selectors) => [selectors.accounts],
            (accounts: AccountApi[]): { key: string; label: string }[] =>
                accounts.map((account) => ({ key: account.id, label: account.name })),
        ],
        productAreaOptions: [
            (selectors) => [selectors.activeProductAreas],
            (productAreas: FeatureRequestProductAreaApi[]): { key: string; label: string }[] =>
                productAreas.map((area) => ({ key: area.id, label: area.name })),
        ],
        editProductAreaOptions: [
            (selectors) => [selectors.productAreas, selectors.editProductAreaIds],
            (
                productAreas: FeatureRequestProductAreaApi[],
                selectedIds: string[]
            ): { key: string; label: string; disabledReason?: string }[] =>
                productAreas
                    .filter((area) => area.is_active || selectedIds.includes(area.id))
                    .map((area) => ({
                        key: area.id,
                        label: area.is_active ? area.name : `${area.name} (inactive)`,
                        disabledReason: area.is_active
                            ? undefined
                            : 'This product area can remain linked but cannot be added',
                    })),
        ],
        submitDisabledReason: [
            (selectors) => [
                selectors.title,
                selectors.description,
                selectors.accountId,
                selectors.productAreaIds,
                selectors.submittingRequest,
            ],
            (
                title: string,
                description: string,
                accountId: string | null,
                productAreaIds: string[],
                submittingRequest: boolean
            ): string | undefined => {
                if (submittingRequest) {
                    return 'Saving request'
                }
                if (!title.trim()) {
                    return 'Enter a title'
                }
                if (!description.trim()) {
                    return 'Enter a description'
                }
                if (!accountId) {
                    return 'Select an account'
                }
                if (productAreaIds.length === 0) {
                    return 'Select at least one product area'
                }
                return undefined
            },
        ],
        editDisabledReason: [
            (selectors) => [
                selectors.editTitle,
                selectors.editDescription,
                selectors.editAccountId,
                selectors.editProductAreaIds,
                selectors.savingRequestChanges,
            ],
            (
                editTitle: string,
                editDescription: string,
                editAccountId: string | null,
                editProductAreaIds: string[],
                savingRequestChanges: boolean
            ): string | undefined => {
                if (savingRequestChanges) {
                    return 'Saving changes'
                }
                if (!editTitle.trim()) {
                    return 'Enter a title'
                }
                if (!editDescription.trim()) {
                    return 'Enter a description'
                }
                if (!editAccountId) {
                    return 'Select an account'
                }
                if (editProductAreaIds.length === 0) {
                    return 'Select at least one product area'
                }
                return undefined
            },
        ],
        productAreaSaveDisabledReason: [
            (selectors) => [selectors.productAreaName, selectors.savingProductArea],
            (productAreaName: string, savingProductArea: boolean): string | undefined => {
                if (savingProductArea) {
                    return 'Saving product area'
                }
                if (!productAreaName.trim()) {
                    return 'Enter a product area name'
                }
                return undefined
            },
        ],
        hasActiveFilters: [
            (selectors) => [
                selectors.searchQuery,
                selectors.statusFilter,
                selectors.priorityFilter,
                selectors.productAreaFilter,
                selectors.accountFilter,
                selectors.archiveState,
            ],
            (
                searchQuery: string,
                statuses: FeatureRequestStatusEnumApi[],
                priorities: FeatureRequestPriorityFilter[],
                productAreas: string[],
                accounts: string[],
                archiveState: FeatureRequestArchiveState
            ): boolean =>
                Boolean(
                    searchQuery.trim() ||
                    statuses.length ||
                    priorities.length ||
                    productAreas.length ||
                    accounts.length ||
                    archiveState !== 'active'
                ),
        ],
        listSearchParams: [
            (selectors) => [
                selectors.searchQuery,
                selectors.statusFilter,
                selectors.priorityFilter,
                selectors.productAreaFilter,
                selectors.accountFilter,
                selectors.archiveState,
                selectors.requestOrdering,
                selectors.featureRequestsPage,
            ],
            (
                searchQuery: string,
                statusFilter: FeatureRequestStatusEnumApi[],
                priorityFilter: FeatureRequestPriorityFilter[],
                productAreaFilter: string[],
                accountFilter: string[],
                archiveState: FeatureRequestArchiveState,
                requestOrdering: FeatureRequestOrdering,
                featureRequestsPage: number
            ): Record<string, string> =>
                featureRequestSearchParams({
                    searchQuery,
                    statusFilter,
                    priorityFilter,
                    productAreaFilter,
                    accountFilter,
                    archiveState,
                    requestOrdering,
                    featureRequestsPage,
                }),
        ],
    }),
    listeners(({ values, actions }) => ({
        setFeatureRequestsPage: () => actions.loadFeatureRequests(),
        setFiltersFromUrl: () => actions.loadFeatureRequests(),
        setSearchQuery: async (_, breakpoint) => {
            await breakpoint(300)
            actions.loadFeatureRequests()
        },
        toggleStatusFilter: () => actions.loadFeatureRequests(),
        togglePriorityFilter: () => actions.loadFeatureRequests(),
        toggleProductAreaFilter: () => actions.loadFeatureRequests(),
        toggleAccountFilter: () => actions.loadFeatureRequests(),
        setArchiveState: () => actions.loadFeatureRequests(),
        setRequestOrdering: () => actions.loadFeatureRequests(),
        clearFilters: () => actions.loadFeatureRequests(),
        openCreateRequest: () => {
            actions.setIdempotencyKey(newIdempotencyKey())
            actions.loadAccounts('')
            actions.loadProductAreas()
        },
        setAccountSearch: async ({ accountSearch }, breakpoint) => {
            await breakpoint(300)
            actions.loadAccounts(accountSearch)
        },
        setActiveRequestId: ({ requestId }) => {
            if (requestId) {
                actions.loadActiveRequest(requestId)
                actions.loadRequestHistory(requestId)
            }
        },
        submitRequest: async () => {
            if (values.submitDisabledReason || !values.accountId) {
                return
            }
            actions.setSubmittingRequest(true)
            try {
                const created = await featureRequestsCreate(values.currentTeamId, {
                    title: values.title.trim(),
                    description: values.description.trim(),
                    account_id: values.accountId,
                    product_area_ids: values.productAreaIds,
                    idempotency_key: values.idempotencyKey,
                })
                actions.closeCreateRequest()
                router.actions.push(urls.customerAnalyticsFeatureRequests(created.id), values.listSearchParams)
            } catch {
                lemonToast.error("Couldn't save the request. Check the fields and try again.")
            } finally {
                actions.setSubmittingRequest(false)
            }
        },
        openProductAreas: () => {
            actions.startNewProductArea()
            actions.loadProductAreas()
        },
        saveProductArea: async () => {
            if (values.productAreaSaveDisabledReason) {
                return
            }
            actions.setSavingProductArea(true)
            try {
                if (values.editingProductAreaId) {
                    await featureRequestProductAreasPartialUpdate(values.currentTeamId, values.editingProductAreaId, {
                        name: values.productAreaName.trim(),
                        display_order: values.productAreaDisplayOrder,
                        is_active: values.productAreaActive,
                    })
                } else {
                    await featureRequestProductAreasCreate(values.currentTeamId, {
                        name: values.productAreaName.trim(),
                        display_order: values.productAreaDisplayOrder,
                        is_active: values.productAreaActive,
                    })
                }
                actions.startNewProductArea()
                actions.loadProductAreas()
                actions.loadFeatureRequests()
            } catch {
                lemonToast.error("Couldn't save the product area. Check the name and try again.")
            } finally {
                actions.setSavingProductArea(false)
            }
        },
        openEditRequest: () => {
            actions.loadAccounts('')
            actions.loadProductAreas()
        },
        saveRequestChanges: async () => {
            if (values.editDisabledReason || !values.activeRequestId || !values.editAccountId) {
                return
            }
            actions.setSavingRequestChanges(true)
            actions.setEditError(null)
            actions.setEditIsStale(false)
            try {
                const updated = await featureRequestsUpdate(values.currentTeamId, values.activeRequestId, {
                    expected_version: values.editExpectedVersion,
                    title: values.editTitle.trim(),
                    description: values.editDescription.trim(),
                    account_id: values.editAccountId,
                    product_area_ids: values.editProductAreaIds,
                    request_status: values.editStatus,
                    request_priority: values.editPriority,
                })
                actions.loadActiveRequestSuccess(updated)
                actions.loadRequestHistory(values.activeRequestId)
                actions.loadFeatureRequests()
                actions.closeEditRequest()
                lemonToast.success('Feature request updated')
            } catch (error) {
                if (error instanceof ApiError && error.status === 409) {
                    actions.setEditError(
                        'This request changed since you opened it. Load the latest version to continue.'
                    )
                    actions.setEditIsStale(true)
                } else {
                    actions.setEditError("Couldn't save the changes. Check the fields and try again.")
                    actions.setEditIsStale(false)
                }
            } finally {
                actions.setSavingRequestChanges(false)
            }
        },
        reloadLatestForEdit: async () => {
            if (!values.activeRequestId) {
                return
            }
            try {
                const latest = await featureRequestsRetrieve(values.currentTeamId, values.activeRequestId)
                actions.loadActiveRequestSuccess(latest)
                actions.setEditExpectedVersion(latest.version)
                actions.setEditError(null)
                actions.setEditIsStale(false)
                lemonToast.info('Latest version loaded. Review your changes and save again.')
            } catch {
                actions.setEditError("Couldn't load the latest version. Try again.")
            }
        },
        archiveActiveRequest: async () => {
            if (!values.activeRequest || values.mutatingArchive) {
                return
            }
            actions.setMutatingArchive(true)
            try {
                const archived = await featureRequestsArchiveCreate(values.currentTeamId, values.activeRequest.id, {
                    expected_version: values.activeRequest.version,
                })
                actions.loadActiveRequestSuccess(archived)
                actions.loadFeatureRequests()
                lemonToast.success('Feature request archived')
            } catch {
                lemonToast.error("Couldn't archive this request. Reload it and try again.")
                actions.loadActiveRequest(values.activeRequest.id)
            } finally {
                actions.setMutatingArchive(false)
            }
        },
        restoreActiveRequest: async () => {
            if (!values.activeRequest || values.mutatingArchive) {
                return
            }
            actions.setMutatingArchive(true)
            try {
                const restored = await featureRequestsRestoreCreate(values.currentTeamId, values.activeRequest.id, {
                    expected_version: values.activeRequest.version,
                })
                actions.loadActiveRequestSuccess(restored)
                actions.loadFeatureRequests()
                lemonToast.success('Feature request restored')
            } catch {
                lemonToast.error("Couldn't restore this request. Reload it and try again.")
                actions.loadActiveRequest(values.activeRequest.id)
            } finally {
                actions.setMutatingArchive(false)
            }
        },
    })),
    actionToUrl(({ values }) => {
        const toUrl = (): [string, Record<string, any>, any, { replace: boolean }] => currentUrlWithFilters(values)
        return {
            setFeatureRequestsPage: toUrl,
            setSearchQuery: toUrl,
            toggleStatusFilter: toUrl,
            togglePriorityFilter: toUrl,
            toggleProductAreaFilter: toUrl,
            toggleAccountFilter: toUrl,
            setArchiveState: toUrl,
            setRequestOrdering: toUrl,
            clearFilters: toUrl,
        }
    }),
    urlToAction(({ actions, values }) => {
        const applyFromUrl = (_: unknown, searchParams: Record<string, any>): void => {
            const parsed = parseFeatureRequestSearchParams(searchParams)
            const current = featureRequestSearchParams({
                searchQuery: values.searchQuery,
                statusFilter: values.statusFilter,
                priorityFilter: values.priorityFilter,
                productAreaFilter: values.productAreaFilter,
                accountFilter: values.accountFilter,
                archiveState: values.archiveState,
                requestOrdering: values.requestOrdering,
                featureRequestsPage: values.featureRequestsPage,
            })
            if (JSON.stringify(current) !== JSON.stringify(featureRequestSearchParams(parsed))) {
                actions.setFiltersFromUrl(parsed)
            }
        }
        return {
            [urls.customerAnalyticsFeatureRequests()]: (params, searchParams) => {
                actions.setActiveRequestId(null)
                applyFromUrl(params, searchParams)
            },
            [urls.customerAnalyticsFeatureRequests(':requestId')]: ({ requestId }, searchParams) => {
                actions.setActiveRequestId(requestId ?? null)
                applyFromUrl({ requestId }, searchParams)
            },
        }
    }),
    afterMount(({ actions }) => {
        actions.loadFeatureRequests()
        actions.loadProductAreas()
        actions.loadAccounts('')
    }),
])
