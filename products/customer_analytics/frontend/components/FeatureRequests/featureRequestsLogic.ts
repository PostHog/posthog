import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import type { Sorting } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api'
import { uploadFile } from 'lib/hooks/useUploadFiles'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { uuid } from 'lib/utils/dom'
import { membersLogic } from 'scenes/organization/membersLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { OrganizationMemberType, TeamPublicType, TeamType, UserBasicType } from '../../../../../frontend/src/types'
import {
    accountsList,
    featureRequestProductAreasCreate,
    featureRequestProductAreasList,
    featureRequestProductAreasPartialUpdate,
    featureRequestsAddAccountCreate,
    featureRequestsAddEvidenceCreate,
    featureRequestsArchiveCreate,
    featureRequestsCreate,
    featureRequestsHistoryList,
    featureRequestsList,
    featureRequestsRemoveEvidenceCreate,
    featureRequestsRestoreCreate,
    featureRequestsRetrieve,
    featureRequestsUpdate,
    featureRequestsUpdateEvidenceCreate,
} from '../../generated/api'
import type {
    AccountApi,
    FeatureRequestAccountApi,
    FeatureRequestAccountLinkApi,
    FeatureRequestApi,
    FeatureRequestEvidenceApi,
    FeatureRequestEvidencePayloadApi,
    FeatureRequestHistoryApi,
    FeatureRequestProductAreaApi,
    FeatureRequestStatusEnumApi,
    PaginatedFeatureRequestListApi,
    RequestPriorityEnumApi,
} from '../../generated/api.schemas'
import { getFeatureRequestBackLabel, getFeatureRequestBackUrl } from './featureRequestNavigation'
import {
    FEATURE_REQUEST_ORDERING_OPTIONS,
    FEATURE_REQUEST_PRIORITY_FILTER_OPTIONS,
    FeatureRequestEvents,
    FEATURE_REQUEST_STATUS_OPTIONS,
    FeatureRequestArchiveState,
    FeatureRequestOrdering,
    FeatureRequestPriorityFilter,
} from './featureRequestOptions'

export const FEATURE_REQUESTS_PAGE_SIZE = 20
export const FEATURE_REQUEST_ACCOUNT_PREVIEW_SIZE = 5

export interface FeatureRequestImage {
    imageId: string
    account: FeatureRequestAccountApi
    evidence: FeatureRequestEvidenceApi
}

export function featureRequestAccountElementId(accountId: string): string {
    return `feature-request-account-${accountId}`
}

export function featureRequestEvidenceElementId(evidenceId: string): string {
    return `feature-request-evidence-${evidenceId}`
}

function hasFeatureRequestEvidence(evidence: FeatureRequestEvidencePayloadApi): boolean {
    return Boolean(
        evidence.summary?.trim() ||
        evidence.customer_quote?.trim() ||
        evidence.source_url?.trim() ||
        evidence.image_ids?.length ||
        evidence.requested_on ||
        evidence.evidence_source !== 'conversation'
    )
}

const FILTER_URL_KEYS = [
    'search',
    'status',
    'priority',
    'product_area',
    'account',
    'created_by',
    'archive',
    'sort',
    'page',
] as const
const FEATURE_REQUEST_SORT_COLUMNS = new Set([
    'title',
    'account',
    'product_area',
    'status',
    'priority',
    'created_by',
    'evidence_count',
    'updated_at',
])
const persistConfig = {
    persist: true,
    prefix: `${window.POSTHOG_APP_CONTEXT?.current_team?.id}_customer_analytics_feature_requests__`,
}
const VALID_STATUSES = new Set(FEATURE_REQUEST_STATUS_OPTIONS.map((option) => option.value))
const VALID_PRIORITIES = new Set(FEATURE_REQUEST_PRIORITY_FILTER_OPTIONS.map((option) => option.value))
const VALID_ORDERINGS = new Set(FEATURE_REQUEST_ORDERING_OPTIONS)
const VALID_ARCHIVE_STATES = new Set<FeatureRequestArchiveState>(['active', 'archived', 'all'])

export interface FeatureRequestListState {
    searchQuery: string
    statusFilter: FeatureRequestStatusEnumApi[]
    priorityFilter: FeatureRequestPriorityFilter[]
    productAreaFilter: string[]
    accountFilter: string[]
    createdByFilter: number[]
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

function parsePositiveIntegerListParam(raw: unknown): number[] {
    const values = typeof raw === 'number' ? [raw] : parseListParam(raw).map(Number)
    return values.filter((value) => Number.isInteger(value) && value > 0)
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
        createdByFilter: parsePositiveIntegerListParam(searchParams.created_by),
        archiveState,
        requestOrdering,
        featureRequestsPage: Number.isInteger(parsedPage) && parsedPage > 0 ? parsedPage : 1,
    }
}

export function featureRequestOrderingToSorting(ordering: FeatureRequestOrdering): Sorting | null {
    const columnKey = ordering.replace(/^-/, '')
    if (!FEATURE_REQUEST_SORT_COLUMNS.has(columnKey)) {
        return null
    }
    return { columnKey, order: ordering.startsWith('-') ? -1 : 1 }
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
    if (values.createdByFilter.length) {
        params.created_by = values.createdByFilter.join(',')
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
    meFirstMembers: OrganizationMemberType[] // membersLogic
    members: OrganizationMemberType[] | null // membersLogic
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
    accountsEvidenceCollapsed: boolean
    accountsLoading: boolean
    activeProductAreas: FeatureRequestProductAreaApi[]
    activeRequest: FeatureRequestApi | null
    activeRequestAccountLinks: FeatureRequestAccountLinkApi[]
    activeRequestError: string | null
    activeRequestEvidenceCount: number
    activeRequestId: string | null
    activeRequestImages: FeatureRequestImage[]
    activeRequestLoading: boolean
    addAccountId: string | null
    addAccountOptions: {
        key: string
        label: string
    }[]
    addingAccount: boolean
    archiveState: FeatureRequestArchiveState
    createRequestOpen: boolean
    createdByFilter: number[]
    creatorById: Record<number, UserBasicType>
    currentTeamId: string
    description: string
    editAccountIds: string[]
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
    editingEvidenceId: string | null
    editingProductAreaId: string | null
    evidenceAccountLinkId: string | null
    evidenceDraftVersion: number
    evidenceError: string | null
    evidenceFilesToUpload: File[]
    evidenceImageIds: string[]
    evidenceModalOpen: boolean
    evidenceQuote: string
    evidenceRequestedOn: string | null
    evidenceSaveDisabledReason: string | undefined
    evidenceSource: string
    evidenceSummary: string
    evidenceUrl: string
    featureRequestBackLabel: string | null
    featureRequestBackUrl: string
    featureRequestsError: string | null
    featureRequestsPage: number
    featureRequestsResponse: PaginatedFeatureRequestListApi
    featureRequestsResponseLoading: boolean
    filteredProductAreas: FeatureRequestProductAreaApi[]
    hasActiveFilters: boolean
    idempotencyKey: string
    listSearchParams: Record<string, string>
    loadedAccountsById: Record<string, AccountApi>
    mutatingArchive: boolean
    priorityFilter: FeatureRequestPriorityFilter[]
    productAreaActive: boolean
    productAreaDisplayOrder: number
    productAreaFilter: string[]
    productAreaFormOpen: boolean
    productAreaFormVersion: number
    productAreaIds: string[]
    productAreaName: string
    productAreaOptions: {
        key: string
        label: string
    }[]
    productAreaSaveDisabledReason: string | undefined
    productAreaSearch: string
    productAreas: FeatureRequestProductAreaApi[]
    productAreasError: string | null
    productAreasLoading: boolean
    productAreasOpen: boolean
    requestAccountsShowingAll: boolean
    requestHistory: FeatureRequestHistoryApi[]
    requestHistoryError: string | null
    requestHistoryLoading: boolean
    requestHistoryShowingAll: boolean
    requestOrdering: FeatureRequestOrdering
    savingEvidence: boolean
    savingProductArea: boolean
    savingRequestChanges: boolean
    searchQuery: string
    selectedAccount: FeatureRequestAccountApi | null
    statusFilter: FeatureRequestStatusEnumApi[]
    submitDisabledReason: string | undefined
    submittingRequest: boolean
    tableSorting: Sorting | null
    title: string
    uploadingEvidenceImages: boolean
    visibleActiveRequestAccountLinks: FeatureRequestAccountLinkApi[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface featureRequestsLogicActions {
    ensureAllMembersLoaded: () => {
        value: true
    } // membersLogic
    archiveActiveRequest: () => {
        value: true
    }
    clearEvidenceFilesToUpload: () => {
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
    closeEvidence: () => {
        value: true
    }
    closeProductAreaForm: () => {
        value: true
    }
    closeProductAreas: () => {
        value: true
    }
    evidenceImageUploaded: (imageId: string) => {
        imageId: string
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
    openAddAccount: () => {
        value: true
    }
    openCreateRequest: () => {
        value: true
    }
    openEditEvidence: (
        accountLink: FeatureRequestAccountLinkApi,
        evidence: FeatureRequestEvidenceApi
    ) => {
        accountLink: FeatureRequestAccountLinkApi
        evidence: FeatureRequestEvidenceApi
    }
    openEditRequest: (featureRequest: FeatureRequestApi) => {
        featureRequest: FeatureRequestApi
    }
    openNewEvidence: (accountLink: FeatureRequestAccountLinkApi) => {
        accountLink: FeatureRequestAccountLinkApi
    }
    openProductAreas: () => {
        value: true
    }
    reloadLatestForEdit: () => {
        value: true
    }
    removeEvidence: () => {
        value: true
    }
    removeEvidenceImage: (imageId: string) => {
        imageId: string
    }
    restoreActiveRequest: () => {
        value: true
    }
    saveEvidence: () => {
        value: true
    }
    saveProductArea: () => {
        value: true
    }
    saveRequestChanges: () => {
        value: true
    }
    setAccountFilter: (accountFilter: string[]) => {
        accountFilter: string[]
    }
    setAccountId: (accountId: string | null) => {
        accountId: string | null
    }
    setAccountSearch: (accountSearch: string) => {
        accountSearch: string
    }
    setAccountsEvidenceCollapsed: (collapsed: boolean) => {
        collapsed: boolean
    }
    setActiveRequestId: (requestId: string | null) => {
        requestId: string | null
    }
    setAddAccountId: (accountId: string | null) => {
        accountId: string | null
    }
    setArchiveState: (archiveState: FeatureRequestArchiveState) => {
        archiveState: FeatureRequestArchiveState
    }
    setCreatedByFilter: (createdByFilter: number[]) => {
        createdByFilter: number[]
    }
    setDescription: (description: string) => {
        description: string
    }
    setEditAccountIds: (editAccountIds: string[]) => {
        editAccountIds: string[]
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
    setEvidenceError: (evidenceError: string | null) => {
        evidenceError: string | null
    }
    setEvidenceQuote: (evidenceQuote: string) => {
        evidenceQuote: string
    }
    setEvidenceRequestedOn: (evidenceRequestedOn: string | null) => {
        evidenceRequestedOn: string | null
    }
    setEvidenceSource: (evidenceSource: string) => {
        evidenceSource: string
    }
    setEvidenceSummary: (evidenceSummary: string) => {
        evidenceSummary: string
    }
    setEvidenceUrl: (evidenceUrl: string) => {
        evidenceUrl: string
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
    setProductAreaFilter: (productAreaFilter: string[]) => {
        productAreaFilter: string[]
    }
    setProductAreaIds: (productAreaIds: string[]) => {
        productAreaIds: string[]
    }
    setProductAreaName: (productAreaName: string) => {
        productAreaName: string
    }
    setProductAreaSearch: (productAreaSearch: string) => {
        productAreaSearch: string
    }
    setRequestAccountsShowingAll: (showingAll: boolean) => {
        showingAll: boolean
    }
    setRequestHistoryShowingAll: (showingAll: boolean) => {
        showingAll: boolean
    }
    setRequestOrdering: (requestOrdering: FeatureRequestOrdering) => {
        requestOrdering: FeatureRequestOrdering
    }
    setSavingEvidence: (savingEvidence: boolean) => {
        savingEvidence: boolean
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
    setSelectedAccount: (selectedAccount: FeatureRequestAccountApi | null) => {
        selectedAccount: FeatureRequestAccountApi | null
    }
    setSubmittingRequest: (submittingRequest: boolean) => {
        submittingRequest: boolean
    }
    setTableSorting: (sorting: Sorting | null) => {
        sorting: Sorting | null
    }
    setTitle: (title: string) => {
        title: string
    }
    setUploadingEvidenceImages: (uploadingEvidenceImages: boolean) => {
        uploadingEvidenceImages: boolean
    }
    showHistoryTarget: (
        accountId: string,
        evidenceId?: string
    ) => {
        accountId: string
        evidenceId: string | undefined
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
    togglePriorityFilter: (requestPriority: FeatureRequestPriorityFilter) => {
        requestPriority: FeatureRequestPriorityFilter
    }
    toggleStatusFilter: (requestStatus: FeatureRequestStatusEnumApi) => {
        requestStatus: FeatureRequestStatusEnumApi
    }
    uploadEvidenceImages: (files: File[]) => {
        files: File[]
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface featureRequestsLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        currentTeamId: (currentTeam: TeamPublicType | TeamType | null) => string
        creatorById: (meFirstMembers: OrganizationMemberType[]) => Record<number, UserBasicType>
        activeProductAreas: (productAreas: FeatureRequestProductAreaApi[]) => FeatureRequestProductAreaApi[]
        filteredProductAreas: (
            productAreas: FeatureRequestProductAreaApi[],
            productAreaSearch: string
        ) => FeatureRequestProductAreaApi[]
        accountOptions: (
            accounts: AccountApi[],
            loadedAccountsById: Record<string, AccountApi>,
            accountFilter: string[],
            selectedAccount: FeatureRequestAccountApi | null,
            activeRequest: FeatureRequestApi | null
        ) => {
            key: string
            label: string
        }[]
        addAccountOptions: (
            accountOptions: {
                key: string
                label: string
            }[],
            activeRequest: FeatureRequestApi | null
        ) => {
            key: string
            label: string
        }[]
        activeRequestAccountLinks: (activeRequest: FeatureRequestApi | null) => FeatureRequestAccountLinkApi[]
        visibleActiveRequestAccountLinks: (
            activeRequestAccountLinks: FeatureRequestAccountLinkApi[],
            requestAccountsShowingAll: boolean
        ) => FeatureRequestAccountLinkApi[]
        activeRequestEvidenceCount: (activeRequestAccountLinks: FeatureRequestAccountLinkApi[]) => number
        activeRequestImages: (activeRequestAccountLinks: FeatureRequestAccountLinkApi[]) => FeatureRequestImage[]
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
            accountId: string | null,
            productAreaIds: string[],
            submittingRequest: boolean,
            uploadingEvidenceImages: boolean
        ) => string | undefined
        editDisabledReason: (
            editTitle: string,
            editAccountIds: string[],
            editProductAreaIds: string[],
            savingRequestChanges: boolean
        ) => string | undefined
        evidenceSaveDisabledReason: (
            addingAccount: boolean,
            addAccountId: string | null,
            evidenceSummary: string,
            evidenceQuote: string,
            evidenceSource: string,
            evidenceUrl: string,
            evidenceRequestedOn: string | null,
            evidenceImageIds: string[],
            uploadingEvidenceImages: boolean,
            savingEvidence: boolean
        ) => string | undefined
        productAreaSaveDisabledReason: (productAreaName: string, savingProductArea: boolean) => string | undefined
        hasActiveFilters: (
            searchQuery: string,
            statusFilter: FeatureRequestStatusEnumApi[],
            priorityFilter: FeatureRequestPriorityFilter[],
            productAreaFilter: string[],
            accountFilter: string[],
            createdByFilter: number[],
            archiveState: FeatureRequestArchiveState
        ) => boolean
        listSearchParams: (
            searchQuery: string,
            statusFilter: FeatureRequestStatusEnumApi[],
            priorityFilter: FeatureRequestPriorityFilter[],
            productAreaFilter: string[],
            accountFilter: string[],
            createdByFilter: number[],
            archiveState: FeatureRequestArchiveState,
            requestOrdering: FeatureRequestOrdering,
            featureRequestsPage: number
        ) => Record<string, string>
        tableSorting: (requestOrdering: FeatureRequestOrdering) => Sorting | null
        featureRequestBackLabel: (searchParams: Record<string, any>) => string | null
        featureRequestBackUrl: (listSearchParams: Record<string, string>, searchParams: Record<string, any>) => string
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
    connect(() => ({
        values: [teamLogic, ['currentTeam'], membersLogic, ['meFirstMembers', 'members']],
        actions: [membersLogic, ['ensureAllMembersLoaded']],
    })),
    actions({
        setActiveRequestId: (requestId: string | null) => ({ requestId }),
        setFeatureRequestsPage: (page: number) => ({ page }),
        setFiltersFromUrl: (filters: FeatureRequestListState) => ({ filters }),
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        toggleStatusFilter: (requestStatus: FeatureRequestStatusEnumApi) => ({ requestStatus }),
        togglePriorityFilter: (requestPriority: FeatureRequestPriorityFilter) => ({ requestPriority }),
        setProductAreaFilter: (productAreaFilter: string[]) => ({ productAreaFilter }),
        setAccountFilter: (accountFilter: string[]) => ({ accountFilter }),
        setCreatedByFilter: (createdByFilter: number[]) => ({ createdByFilter }),
        setArchiveState: (archiveState: FeatureRequestArchiveState) => ({ archiveState }),
        setRequestOrdering: (requestOrdering: FeatureRequestOrdering) => ({ requestOrdering }),
        setTableSorting: (sorting: Sorting | null) => ({ sorting }),
        clearFilters: true,
        openCreateRequest: true,
        closeCreateRequest: true,
        setTitle: (title: string) => ({ title }),
        setDescription: (description: string) => ({ description }),
        setAccountId: (accountId: string | null) => ({ accountId }),
        setSelectedAccount: (selectedAccount: FeatureRequestAccountApi | null) => ({ selectedAccount }),
        setAccountSearch: (accountSearch: string) => ({ accountSearch }),
        setProductAreaIds: (productAreaIds: string[]) => ({ productAreaIds }),
        setIdempotencyKey: (idempotencyKey: string) => ({ idempotencyKey }),
        submitRequest: true,
        setSubmittingRequest: (submittingRequest: boolean) => ({ submittingRequest }),
        openProductAreas: true,
        closeProductAreas: true,
        closeProductAreaForm: true,
        startNewProductArea: true,
        startEditingProductArea: (productArea: FeatureRequestProductAreaApi) => ({ productArea }),
        setProductAreaName: (productAreaName: string) => ({ productAreaName }),
        setProductAreaSearch: (productAreaSearch: string) => ({ productAreaSearch }),
        setProductAreaDisplayOrder: (productAreaDisplayOrder: number) => ({ productAreaDisplayOrder }),
        setProductAreaActive: (productAreaActive: boolean) => ({ productAreaActive }),
        saveProductArea: true,
        setSavingProductArea: (savingProductArea: boolean) => ({ savingProductArea }),
        openEditRequest: (featureRequest: FeatureRequestApi) => ({ featureRequest }),
        closeEditRequest: true,
        setEditTitle: (editTitle: string) => ({ editTitle }),
        setEditDescription: (editDescription: string) => ({ editDescription }),
        setEditAccountIds: (editAccountIds: string[]) => ({ editAccountIds }),
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
        setRequestAccountsShowingAll: (showingAll: boolean) => ({ showingAll }),
        setAccountsEvidenceCollapsed: (collapsed: boolean) => ({ collapsed }),
        showHistoryTarget: (accountId: string, evidenceId?: string) => ({ accountId, evidenceId }),
        openAddAccount: true,
        setAddAccountId: (accountId: string | null) => ({ accountId }),
        openNewEvidence: (accountLink: FeatureRequestAccountLinkApi) => ({ accountLink }),
        openEditEvidence: (accountLink: FeatureRequestAccountLinkApi, evidence: FeatureRequestEvidenceApi) => ({
            accountLink,
            evidence,
        }),
        closeEvidence: true,
        setEvidenceSummary: (evidenceSummary: string) => ({ evidenceSummary }),
        setEvidenceQuote: (evidenceQuote: string) => ({ evidenceQuote }),
        setEvidenceSource: (evidenceSource: string) => ({ evidenceSource }),
        setEvidenceUrl: (evidenceUrl: string) => ({ evidenceUrl }),
        setEvidenceRequestedOn: (evidenceRequestedOn: string | null) => ({ evidenceRequestedOn }),
        setEvidenceError: (evidenceError: string | null) => ({ evidenceError }),
        uploadEvidenceImages: (files: File[]) => ({ files }),
        clearEvidenceFilesToUpload: true,
        evidenceImageUploaded: (imageId: string) => ({ imageId }),
        removeEvidenceImage: (imageId: string) => ({ imageId }),
        setUploadingEvidenceImages: (uploadingEvidenceImages: boolean) => ({ uploadingEvidenceImages }),
        saveEvidence: true,
        removeEvidence: true,
        setSavingEvidence: (savingEvidence: boolean) => ({ savingEvidence }),
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
                        created_by_ids: values.createdByFilter.length ? values.createdByFilter : undefined,
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
                setProductAreaFilter: () => 1,
                setAccountFilter: () => 1,
                setCreatedByFilter: () => 1,
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
            persistConfig,
            {
                toggleStatusFilter: (state, { requestStatus }) => toggleValue(state, requestStatus),
                setFiltersFromUrl: (_, { filters }) => filters.statusFilter,
                clearFilters: () => [],
            },
        ],
        priorityFilter: [
            [] as FeatureRequestPriorityFilter[],
            persistConfig,
            {
                togglePriorityFilter: (state, { requestPriority }) => toggleValue(state, requestPriority),
                setFiltersFromUrl: (_, { filters }) => filters.priorityFilter,
                clearFilters: () => [],
            },
        ],
        productAreaFilter: [
            [] as string[],
            persistConfig,
            {
                setProductAreaFilter: (_, { productAreaFilter }) => productAreaFilter,
                setFiltersFromUrl: (_, { filters }) => filters.productAreaFilter,
                clearFilters: () => [],
            },
        ],
        accountFilter: [
            [] as string[],
            persistConfig,
            {
                setAccountFilter: (_, { accountFilter }) => accountFilter,
                setFiltersFromUrl: (_, { filters }) => filters.accountFilter,
                clearFilters: () => [],
            },
        ],
        loadedAccountsById: [
            {} as Record<string, AccountApi>,
            {
                loadAccountsSuccess: (state, { accounts }) => ({
                    ...state,
                    ...Object.fromEntries(accounts.map((account) => [account.id, account])),
                }),
            },
        ],
        createdByFilter: [
            [] as number[],
            persistConfig,
            {
                setCreatedByFilter: (_, { createdByFilter }) => createdByFilter,
                setFiltersFromUrl: (_, { filters }) => filters.createdByFilter,
                clearFilters: () => [],
            },
        ],
        archiveState: [
            'active' as FeatureRequestArchiveState,
            persistConfig,
            {
                setArchiveState: (_, { archiveState }) => archiveState,
                setFiltersFromUrl: (_, { filters }) => filters.archiveState,
                clearFilters: () => 'active',
            },
        ],
        requestOrdering: [
            '-updated_at' as FeatureRequestOrdering,
            persistConfig,
            {
                setRequestOrdering: (_, { requestOrdering }) => requestOrdering,
                setFiltersFromUrl: (_, { filters }) => filters.requestOrdering,
            },
        ],
        accountSearch: ['', { setAccountSearch: (_, { accountSearch }) => accountSearch }],
        selectedAccount: [
            null as FeatureRequestAccountApi | null,
            {
                setSelectedAccount: (_, { selectedAccount }) => selectedAccount,
                openAddAccount: () => null,
                openEditRequest: (_, { featureRequest }) => featureRequest.account,
                closeCreateRequest: () => null,
                closeEditRequest: () => null,
                closeEvidence: () => null,
            },
        ],
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
        requestAccountsShowingAll: [
            false,
            {
                setRequestAccountsShowingAll: (_, { showingAll }) => showingAll,
                showHistoryTarget: () => true,
                loadActiveRequest: () => false,
                setActiveRequestId: () => false,
            },
        ],
        accountsEvidenceCollapsed: [
            false,
            {
                setAccountsEvidenceCollapsed: (_, { collapsed }) => collapsed,
                showHistoryTarget: () => false,
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
        productAreaSearch: [
            '',
            {
                setProductAreaSearch: (_, { productAreaSearch }) => productAreaSearch,
                closeProductAreas: () => '',
            },
        ],
        productAreaFormOpen: [
            false,
            {
                startNewProductArea: () => true,
                startEditingProductArea: () => true,
                closeProductAreaForm: () => false,
                closeProductAreas: () => false,
            },
        ],
        productAreaFormVersion: [
            0,
            {
                startNewProductArea: (state) => state + 1,
                startEditingProductArea: (state) => state + 1,
                closeProductAreaForm: (state) => state + 1,
                closeProductAreas: (state) => state + 1,
            },
        ],
        editingProductAreaId: [
            null as string | null,
            {
                startNewProductArea: () => null,
                startEditingProductArea: (_, { productArea }) => productArea.id,
                closeProductAreaForm: () => null,
                closeProductAreas: () => null,
            },
        ],
        productAreaName: [
            '',
            {
                startNewProductArea: () => '',
                startEditingProductArea: (_, { productArea }) => productArea.name,
                setProductAreaName: (_, { productAreaName }) => productAreaName,
                closeProductAreaForm: () => '',
                closeProductAreas: () => '',
            },
        ],
        productAreaDisplayOrder: [
            0,
            {
                startNewProductArea: () => 0,
                startEditingProductArea: (_, { productArea }) => productArea.display_order ?? 0,
                setProductAreaDisplayOrder: (_, { productAreaDisplayOrder }) => productAreaDisplayOrder,
                closeProductAreaForm: () => 0,
                closeProductAreas: () => 0,
            },
        ],
        productAreaActive: [
            true,
            {
                startNewProductArea: () => true,
                startEditingProductArea: (_, { productArea }) => productArea.is_active ?? true,
                setProductAreaActive: (_, { productAreaActive }) => productAreaActive,
                closeProductAreaForm: () => true,
                closeProductAreas: () => true,
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
        editAccountIds: [
            [] as string[],
            {
                openEditRequest: (_, { featureRequest }) => featureRequest.account_links.map((link) => link.account.id),
                setEditAccountIds: (_, { editAccountIds }) => editAccountIds,
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
        evidenceModalOpen: [
            false,
            {
                openAddAccount: () => true,
                openNewEvidence: () => true,
                openEditEvidence: () => true,
                closeEvidence: () => false,
            },
        ],
        addingAccount: [
            false,
            {
                openAddAccount: () => true,
                openNewEvidence: () => false,
                openEditEvidence: () => false,
                closeEvidence: () => false,
            },
        ],
        addAccountId: [
            null as string | null,
            {
                openAddAccount: () => null,
                setAddAccountId: (_, { accountId }) => accountId,
                closeEvidence: () => null,
            },
        ],
        evidenceAccountLinkId: [
            null as string | null,
            {
                openAddAccount: () => null,
                openNewEvidence: (_, { accountLink }) => accountLink.id,
                openEditEvidence: (_, { accountLink }) => accountLink.id,
                closeEvidence: () => null,
            },
        ],
        editingEvidenceId: [
            null as string | null,
            {
                openAddAccount: () => null,
                openNewEvidence: () => null,
                openEditEvidence: (_, { evidence }) => evidence.id,
                closeEvidence: () => null,
            },
        ],
        evidenceSummary: [
            '',
            {
                openCreateRequest: () => '',
                closeCreateRequest: () => '',
                openAddAccount: () => '',
                openNewEvidence: () => '',
                openEditEvidence: (_, { evidence }) => evidence.summary,
                setEvidenceSummary: (_, { evidenceSummary }) => evidenceSummary,
            },
        ],
        evidenceQuote: [
            '',
            {
                openCreateRequest: () => '',
                closeCreateRequest: () => '',
                openAddAccount: () => '',
                openNewEvidence: () => '',
                openEditEvidence: (_, { evidence }) => evidence.customer_quote,
                setEvidenceQuote: (_, { evidenceQuote }) => evidenceQuote,
            },
        ],
        evidenceSource: [
            'conversation',
            {
                openCreateRequest: () => 'conversation',
                closeCreateRequest: () => 'conversation',
                openAddAccount: () => 'conversation',
                openNewEvidence: () => 'conversation',
                openEditEvidence: (_, { evidence }) => evidence.evidence_source,
                setEvidenceSource: (_, { evidenceSource }) => evidenceSource,
            },
        ],
        evidenceUrl: [
            '',
            {
                openCreateRequest: () => '',
                closeCreateRequest: () => '',
                openAddAccount: () => '',
                openNewEvidence: () => '',
                openEditEvidence: (_, { evidence }) => evidence.source_url,
                setEvidenceUrl: (_, { evidenceUrl }) => evidenceUrl,
            },
        ],
        evidenceRequestedOn: [
            null as string | null,
            {
                openCreateRequest: () => null,
                closeCreateRequest: () => null,
                openAddAccount: () => null,
                openNewEvidence: () => null,
                openEditEvidence: (_, { evidence }) => evidence.requested_on,
                setEvidenceRequestedOn: (_, { evidenceRequestedOn }) => evidenceRequestedOn,
            },
        ],
        evidenceDraftVersion: [
            0,
            {
                openCreateRequest: (state) => state + 1,
                closeCreateRequest: (state) => state + 1,
                openAddAccount: (state) => state + 1,
                openNewEvidence: (state) => state + 1,
                openEditEvidence: (state) => state + 1,
                closeEvidence: (state) => state + 1,
                setActiveRequestId: (state) => state + 1,
            },
        ],
        evidenceFilesToUpload: [
            [] as File[],
            {
                openCreateRequest: () => [],
                closeCreateRequest: () => [],
                openAddAccount: () => [],
                openNewEvidence: () => [],
                openEditEvidence: () => [],
                uploadEvidenceImages: (_, { files }) => files,
                clearEvidenceFilesToUpload: () => [],
                closeEvidence: () => [],
            },
        ],
        evidenceImageIds: [
            [] as string[],
            {
                openCreateRequest: () => [],
                closeCreateRequest: () => [],
                openAddAccount: () => [],
                openNewEvidence: () => [],
                openEditEvidence: (_, { evidence }) => [...evidence.image_ids],
                evidenceImageUploaded: (state, { imageId }) => (state.includes(imageId) ? state : [...state, imageId]),
                removeEvidenceImage: (state, { imageId }) => state.filter((id) => id !== imageId),
                closeEvidence: () => [],
            },
        ],
        uploadingEvidenceImages: [
            false,
            { setUploadingEvidenceImages: (_, { uploadingEvidenceImages }) => uploadingEvidenceImages },
        ],
        evidenceError: [
            null as string | null,
            {
                openCreateRequest: () => null,
                closeCreateRequest: () => null,
                openAddAccount: () => null,
                openNewEvidence: () => null,
                openEditEvidence: () => null,
                closeEvidence: () => null,
                setEvidenceError: (_, { evidenceError }) => evidenceError,
            },
        ],
        savingEvidence: [false, { setSavingEvidence: (_, { savingEvidence }) => savingEvidence }],
    }),
    selectors({
        currentTeamId: [
            (selectors) => [selectors.currentTeam],
            (currentTeam: TeamPublicType | TeamType | null): string => String(currentTeam?.id ?? ''),
        ],
        creatorById: [
            (selectors) => [selectors.meFirstMembers],
            (meFirstMembers: OrganizationMemberType[]): Record<number, UserBasicType> =>
                Object.fromEntries(meFirstMembers.map((member) => [member.user.id, member.user])),
        ],
        activeProductAreas: [
            (selectors) => [selectors.productAreas],
            (productAreas: FeatureRequestProductAreaApi[]): FeatureRequestProductAreaApi[] =>
                productAreas.filter((area) => area.is_active),
        ],
        filteredProductAreas: [
            (selectors) => [selectors.productAreas, selectors.productAreaSearch],
            (
                productAreas: FeatureRequestProductAreaApi[],
                productAreaSearch: string
            ): FeatureRequestProductAreaApi[] => {
                const normalizedSearch = productAreaSearch.trim().toLocaleLowerCase()
                return normalizedSearch
                    ? productAreas.filter((area) => area.name.toLocaleLowerCase().includes(normalizedSearch))
                    : productAreas
            },
        ],
        accountOptions: [
            (selectors) => [
                selectors.accounts,
                selectors.loadedAccountsById,
                selectors.accountFilter,
                selectors.selectedAccount,
                selectors.activeRequest,
            ],
            (
                accounts: AccountApi[],
                loadedAccountsById: Record<string, AccountApi>,
                accountFilter: string[],
                selectedAccount: FeatureRequestAccountApi | null,
                activeRequest: FeatureRequestApi | null
            ): { key: string; label: string }[] => {
                const accountById = new Map<string, AccountApi | FeatureRequestAccountApi>(
                    accounts.map((account) => [account.id, account])
                )
                for (const accountId of accountFilter) {
                    const selectedFilterAccount = loadedAccountsById[accountId]
                    if (selectedFilterAccount && !accountById.has(accountId)) {
                        accountById.set(accountId, selectedFilterAccount)
                    }
                }
                if (selectedAccount && !accountById.has(selectedAccount.id)) {
                    accountById.set(selectedAccount.id, selectedAccount)
                }
                for (const link of activeRequest?.account_links ?? []) {
                    if (!accountById.has(link.account.id)) {
                        accountById.set(link.account.id, link.account)
                    }
                }
                return [...accountById.values()].map((account) => ({
                    key: account.id,
                    label: account.name,
                }))
            },
        ],
        addAccountOptions: [
            (selectors) => [selectors.accountOptions, selectors.activeRequest],
            (
                accountOptions: { key: string; label: string }[],
                activeRequest: FeatureRequestApi | null
            ): { key: string; label: string }[] => {
                const linkedAccountIds = new Set(activeRequest?.account_links.map((link) => link.account.id) ?? [])
                return accountOptions.filter((option) => !linkedAccountIds.has(option.key))
            },
        ],
        activeRequestAccountLinks: [
            (selectors) => [selectors.activeRequest],
            (activeRequest: FeatureRequestApi | null): FeatureRequestAccountLinkApi[] =>
                [...(activeRequest?.account_links ?? [])].sort(
                    (first, second) =>
                        second.evidence.length - first.evidence.length ||
                        first.account.name.localeCompare(second.account.name)
                ),
        ],
        visibleActiveRequestAccountLinks: [
            (selectors) => [selectors.activeRequestAccountLinks, selectors.requestAccountsShowingAll],
            (accountLinks: FeatureRequestAccountLinkApi[], showingAll: boolean): FeatureRequestAccountLinkApi[] =>
                showingAll ? accountLinks : accountLinks.slice(0, FEATURE_REQUEST_ACCOUNT_PREVIEW_SIZE),
        ],
        activeRequestEvidenceCount: [
            (selectors) => [selectors.activeRequestAccountLinks],
            (accountLinks: FeatureRequestAccountLinkApi[]): number =>
                accountLinks.reduce((total, accountLink) => total + accountLink.evidence.length, 0),
        ],
        activeRequestImages: [
            (selectors) => [selectors.activeRequestAccountLinks],
            (accountLinks: FeatureRequestAccountLinkApi[]): FeatureRequestImage[] =>
                accountLinks.flatMap((accountLink) =>
                    accountLink.evidence.flatMap((evidence) =>
                        evidence.image_ids.map((imageId) => ({
                            imageId,
                            account: accountLink.account,
                            evidence,
                        }))
                    )
                ),
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
                selectors.accountId,
                selectors.productAreaIds,
                selectors.submittingRequest,
                selectors.uploadingEvidenceImages,
            ],
            (
                title: string,
                accountId: string | null,
                productAreaIds: string[],
                submittingRequest: boolean,
                uploadingEvidenceImages: boolean
            ): string | undefined => {
                if (uploadingEvidenceImages) {
                    return 'Uploading images'
                }
                if (submittingRequest) {
                    return 'Saving request'
                }
                if (!title.trim()) {
                    return 'Enter a title'
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
                selectors.editAccountIds,
                selectors.editProductAreaIds,
                selectors.savingRequestChanges,
            ],
            (
                editTitle: string,
                editAccountIds: string[],
                editProductAreaIds: string[],
                savingRequestChanges: boolean
            ): string | undefined => {
                if (savingRequestChanges) {
                    return 'Saving changes'
                }
                if (!editTitle.trim()) {
                    return 'Enter a title'
                }
                if (editAccountIds.length === 0) {
                    return 'Select at least one account'
                }
                if (editProductAreaIds.length === 0) {
                    return 'Select at least one product area'
                }
                return undefined
            },
        ],
        evidenceSaveDisabledReason: [
            (selectors) => [
                selectors.addingAccount,
                selectors.addAccountId,
                selectors.evidenceSummary,
                selectors.evidenceQuote,
                selectors.evidenceSource,
                selectors.evidenceUrl,
                selectors.evidenceRequestedOn,
                selectors.evidenceImageIds,
                selectors.uploadingEvidenceImages,
                selectors.savingEvidence,
            ],
            (
                addingAccount: boolean,
                addAccountId: string | null,
                summary: string,
                quote: string,
                source: string,
                sourceUrl: string,
                requestedOn: string | null,
                imageIds: string[],
                uploadingImages: boolean,
                saving: boolean
            ): string | undefined => {
                if (uploadingImages) {
                    return 'Uploading images'
                }
                if (saving) {
                    return addingAccount ? 'Adding account' : 'Saving evidence'
                }
                if (addingAccount && !addAccountId) {
                    return 'Select an account'
                }
                if (
                    !addingAccount &&
                    !hasFeatureRequestEvidence({
                        summary,
                        customer_quote: quote,
                        evidence_source: source,
                        source_url: sourceUrl,
                        requested_on: requestedOn,
                        image_ids: imageIds,
                    })
                ) {
                    return 'Enter a summary, customer quote, source URL, image, request date, or change the source'
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
                selectors.createdByFilter,
                selectors.archiveState,
            ],
            (
                searchQuery: string,
                statuses: FeatureRequestStatusEnumApi[],
                priorities: FeatureRequestPriorityFilter[],
                productAreas: string[],
                accounts: string[],
                createdByFilter: number[],
                archiveState: FeatureRequestArchiveState
            ): boolean =>
                Boolean(
                    searchQuery.trim() ||
                    statuses.length ||
                    priorities.length ||
                    productAreas.length ||
                    accounts.length ||
                    createdByFilter.length ||
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
                selectors.createdByFilter,
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
                createdByFilter: number[],
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
                    createdByFilter,
                    archiveState,
                    requestOrdering,
                    featureRequestsPage,
                }),
        ],
        tableSorting: [
            (selectors) => [selectors.requestOrdering],
            (requestOrdering: FeatureRequestOrdering): Sorting | null =>
                featureRequestOrderingToSorting(requestOrdering),
        ],
        featureRequestBackLabel: [
            () => [router.selectors.searchParams],
            (searchParams: Record<string, any>): string | null => getFeatureRequestBackLabel(searchParams.origin),
        ],
        featureRequestBackUrl: [
            (selectors) => [selectors.listSearchParams, router.selectors.searchParams],
            (listSearchParams: Record<string, string>, searchParams: Record<string, any>): string =>
                getFeatureRequestBackUrl(searchParams.origin, listSearchParams),
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
        setProductAreaFilter: () => actions.loadFeatureRequests(),
        setAccountFilter: () => actions.loadFeatureRequests(),
        setCreatedByFilter: () => actions.loadFeatureRequests(),
        setArchiveState: () => actions.loadFeatureRequests(),
        setRequestOrdering: () => actions.loadFeatureRequests(),
        setTableSorting: ({ sorting }) => {
            if (!sorting) {
                return
            }
            const requestOrdering = `${sorting.order === -1 ? '-' : ''}${sorting.columnKey}` as FeatureRequestOrdering
            if (VALID_ORDERINGS.has(requestOrdering)) {
                posthog.capture(FeatureRequestEvents.Sorted, {
                    column: sorting.columnKey,
                    direction: sorting.order === -1 ? 'desc' : 'asc',
                })
                actions.setRequestOrdering(requestOrdering)
            }
        },
        clearFilters: () => actions.loadFeatureRequests(),
        openCreateRequest: () => {
            actions.setIdempotencyKey(newIdempotencyKey())
            actions.loadAccounts('')
            actions.loadProductAreas()
        },
        openAddAccount: () => actions.loadAccounts(''),
        showHistoryTarget: ({ accountId, evidenceId }) => {
            window.setTimeout(() => {
                const evidenceElement = evidenceId
                    ? document.getElementById(featureRequestEvidenceElementId(evidenceId))
                    : null
                const accountElement = document.getElementById(featureRequestAccountElementId(accountId))
                const targetElement = evidenceElement ?? accountElement
                targetElement?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
            }, 0)
        },
        setAddAccountId: ({ accountId }) => {
            actions.setSelectedAccount(
                accountId ? (values.accounts.find((account) => account.id === accountId) ?? null) : null
            )
        },
        setAccountId: ({ accountId }) => {
            actions.setSelectedAccount(
                accountId ? (values.accounts.find((account) => account.id === accountId) ?? null) : null
            )
        },
        setEditAccountId: ({ editAccountId }) => {
            actions.setSelectedAccount(
                editAccountId ? (values.accounts.find((account) => account.id === editAccountId) ?? null) : null
            )
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
        loadActiveRequestSuccess: ({ activeRequest }) => {
            const accountId = router.values.searchParams.evidence_account
            if (typeof accountId !== 'string' || activeRequest.is_archived) {
                return
            }
            const accountLink = activeRequest.account_links.find((link) => link.account.id === accountId)
            if (accountLink) {
                actions.openNewEvidence(accountLink)
            }
        },
        closeEvidence: () => {
            if (!router.values.searchParams.evidence_account) {
                return
            }
            const searchParams = { ...router.values.searchParams }
            delete searchParams.evidence_account
            router.actions.replace(router.values.location.pathname, searchParams, router.values.hashParams)
        },
        submitRequest: async () => {
            if (values.submitDisabledReason || !values.accountId) {
                return
            }
            actions.setSubmittingRequest(true)
            try {
                const evidence = {
                    summary: values.evidenceSummary.trim(),
                    customer_quote: values.evidenceQuote.trim(),
                    evidence_source: values.evidenceSource,
                    source_url: values.evidenceUrl.trim(),
                    requested_on: values.evidenceRequestedOn,
                    image_ids: values.evidenceImageIds,
                }
                const hasEvidence = hasFeatureRequestEvidence(evidence)
                const created = await featureRequestsCreate(values.currentTeamId, {
                    title: values.title.trim(),
                    description: values.description.trim(),
                    account_id: values.accountId,
                    product_area_ids: values.productAreaIds,
                    idempotency_key: values.idempotencyKey,
                    evidence: hasEvidence ? evidence : undefined,
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
            actions.closeProductAreaForm()
            actions.loadProductAreas()
        },
        saveProductArea: async () => {
            if (values.productAreaSaveDisabledReason) {
                return
            }
            const productAreaFormVersion = values.productAreaFormVersion
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
                if (values.productAreaFormVersion === productAreaFormVersion) {
                    actions.closeProductAreaForm()
                }
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
            if (values.editDisabledReason || !values.activeRequestId) {
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
                    account_ids: values.editAccountIds,
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
        uploadEvidenceImages: async ({ files }) => {
            if (files.length === 0 || values.uploadingEvidenceImages) {
                return
            }
            const evidenceDraftVersion = values.evidenceDraftVersion
            actions.setUploadingEvidenceImages(true)
            try {
                for (const file of files) {
                    const uploadedImage = await uploadFile(file)
                    if (values.evidenceDraftVersion !== evidenceDraftVersion) {
                        return
                    }
                    actions.evidenceImageUploaded(uploadedImage.id)
                }
            } catch {
                lemonToast.error("Couldn't upload one of the images. Try again.")
            } finally {
                actions.setUploadingEvidenceImages(false)
                actions.clearEvidenceFilesToUpload()
            }
        },
        saveEvidence: async () => {
            if (values.evidenceSaveDisabledReason || !values.activeRequest) {
                return
            }
            const addingAccount = values.addingAccount
            const editingEvidenceId = values.editingEvidenceId
            const evidenceAccountLinkId = values.evidenceAccountLinkId
            if (!addingAccount && !evidenceAccountLinkId) {
                return
            }
            actions.setSavingEvidence(true)
            actions.setEvidenceError(null)
            try {
                const evidenceFields = {
                    summary: values.evidenceSummary.trim(),
                    customer_quote: values.evidenceQuote.trim(),
                    evidence_source: values.evidenceSource,
                    source_url: values.evidenceUrl.trim(),
                    requested_on: values.evidenceRequestedOn,
                    image_ids: values.evidenceImageIds,
                }
                const hasEvidence = hasFeatureRequestEvidence(evidenceFields)
                let updated: FeatureRequestApi
                if (addingAccount && values.addAccountId) {
                    updated = await featureRequestsAddAccountCreate(values.currentTeamId, values.activeRequest.id, {
                        expected_version: values.activeRequest.version,
                        account_id: values.addAccountId,
                        evidence: hasEvidence ? evidenceFields : undefined,
                    })
                } else if (editingEvidenceId) {
                    updated = await featureRequestsUpdateEvidenceCreate(values.currentTeamId, values.activeRequest.id, {
                        expected_version: values.activeRequest.version,
                        ...evidenceFields,
                        evidence_id: editingEvidenceId,
                    })
                } else if (evidenceAccountLinkId) {
                    updated = await featureRequestsAddEvidenceCreate(values.currentTeamId, values.activeRequest.id, {
                        expected_version: values.activeRequest.version,
                        ...evidenceFields,
                        account_link_id: evidenceAccountLinkId,
                    })
                } else {
                    return
                }
                actions.loadActiveRequestSuccess(updated)
                actions.loadRequestHistory(updated.id)
                actions.loadFeatureRequests()
                actions.closeEvidence()
                lemonToast.success(
                    addingAccount
                        ? hasEvidence
                            ? 'Account and evidence added'
                            : 'Account added'
                        : editingEvidenceId
                          ? 'Evidence updated'
                          : 'Evidence added'
                )
            } catch (error) {
                actions.setEvidenceError(
                    error instanceof ApiError && error.status === 409
                        ? 'This request changed. Close this form, reload the request, and try again.'
                        : addingAccount
                          ? "Couldn't add the account. Check the fields and try again."
                          : "Couldn't save the evidence. Check the fields and try again."
                )
            } finally {
                actions.setSavingEvidence(false)
            }
        },
        removeEvidence: async () => {
            if (!values.activeRequest || !values.editingEvidenceId || values.savingEvidence) {
                return
            }
            actions.setSavingEvidence(true)
            actions.setEvidenceError(null)
            try {
                const updated = await featureRequestsRemoveEvidenceCreate(
                    values.currentTeamId,
                    values.activeRequest.id,
                    {
                        expected_version: values.activeRequest.version,
                        evidence_id: values.editingEvidenceId,
                    }
                )
                actions.loadActiveRequestSuccess(updated)
                actions.loadRequestHistory(updated.id)
                actions.loadFeatureRequests()
                actions.closeEvidence()
                lemonToast.success('Evidence removed')
            } catch (error) {
                actions.setEvidenceError(
                    error instanceof ApiError && error.status === 409
                        ? 'This request changed. Close this form, reload the request, and try again.'
                        : "Couldn't remove the evidence. Try again."
                )
            } finally {
                actions.setSavingEvidence(false)
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
            setProductAreaFilter: toUrl,
            setAccountFilter: toUrl,
            setCreatedByFilter: toUrl,
            setArchiveState: toUrl,
            setRequestOrdering: toUrl,
            clearFilters: toUrl,
        }
    }),
    urlToAction(({ actions, values }) => {
        const applyFromUrl = (_: unknown, searchParams: Record<string, any>): void => {
            const parsed = parseFeatureRequestSearchParams(searchParams)
            const hasFiltersInUrl = FILTER_URL_KEYS.some((key) => key !== 'page' && searchParams[key] !== undefined)
            const filters = hasFiltersInUrl
                ? parsed
                : {
                      searchQuery: parsed.searchQuery,
                      statusFilter: values.statusFilter,
                      priorityFilter: values.priorityFilter,
                      productAreaFilter: values.productAreaFilter,
                      accountFilter: values.accountFilter,
                      createdByFilter: values.createdByFilter,
                      archiveState: values.archiveState,
                      requestOrdering: values.requestOrdering,
                      featureRequestsPage: parsed.featureRequestsPage,
                  }
            const current = featureRequestSearchParams({
                searchQuery: values.searchQuery,
                statusFilter: values.statusFilter,
                priorityFilter: values.priorityFilter,
                productAreaFilter: values.productAreaFilter,
                accountFilter: values.accountFilter,
                createdByFilter: values.createdByFilter,
                archiveState: values.archiveState,
                requestOrdering: values.requestOrdering,
                featureRequestsPage: values.featureRequestsPage,
            })
            if (JSON.stringify(current) !== JSON.stringify(featureRequestSearchParams(filters))) {
                actions.setFiltersFromUrl(filters)
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
        actions.ensureAllMembersLoaded()
    }),
])
