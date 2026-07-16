import { MakeLogicType, actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { PaginationManual } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { objectsEqual } from 'lib/utils/objects'
import { parseNumericArrayFilter, parseTagsFilter, toParams } from 'lib/utils/url'
import { handleFlagApprovalRequired } from 'scenes/feature-flags/updateFlagActiveInProject'
import { projectLogic } from 'scenes/projectLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { ActivityScope, Breadcrumb, FeatureFlagType } from '~/types'

import { FeatureFlagArchivedSource, reportFeatureFlagArchived } from './featureFlagArchiveDialog'

export const FLAGS_PER_PAGE = 100

export function flagMatchesSearch(flag: FeatureFlagType, search?: string): boolean {
    if (!search?.trim()) {
        return true
    }

    const searchValue = search.trim().toLowerCase()
    const keyLower = flag.key.toLowerCase()
    const nameLower = flag.name?.toLowerCase() || ''

    // Get experiment names from experiment_set_metadata, filtering out null/undefined names
    const experimentNames =
        flag.experiment_set_metadata
            ?.map((exp) => exp.name?.toLowerCase())
            .filter(Boolean)
            .join(' ') || ''

    // Use regex pattern matching like the backend - escape metacharacters then replace spaces with word boundary pattern
    const escapedSearchValue = searchValue.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const regexPattern = escapedSearchValue.replace(/\s+/g, '[\\s\\-_]*')

    try {
        const regex = new RegExp(regexPattern, 'i')
        return regex.test(keyLower) || regex.test(nameLower) || regex.test(experimentNames)
    } catch {
        // Fallback to simple case-insensitive substring search if regex fails
        return (
            keyLower.includes(searchValue) || nameLower.includes(searchValue) || experimentNames.includes(searchValue)
        )
    }
}

export function flagMatchesStatus(flag: FeatureFlagType, active?: string): boolean {
    if (!active) {
        return true
    }
    if (active === 'true') {
        return flag.active
    }
    if (active === 'false') {
        return !flag.active
    }
    if (active === 'STALE') {
        return flag.status === 'STALE'
    }
    return true
}

export function flagMatchesType(flag: FeatureFlagType, type?: string): boolean {
    if (!type) {
        return true
    }

    const isMultivariate = !!flag.filters.multivariate?.variants?.length

    if (type === 'boolean') {
        return !isMultivariate
    }
    if (type === 'multivariant') {
        return isMultivariate
    }
    if (type === 'experiment') {
        return !!flag.experiment_set?.length
    }
    if (type === 'remote_config') {
        return flag.is_remote_configuration
    }

    return true
}

export function flagMatchesFilters(flag: FeatureFlagType, filters: FeatureFlagsFilters): boolean {
    return (
        flagMatchesSearch(flag, filters.search) &&
        flagMatchesStatus(flag, filters.active) &&
        flagMatchesType(flag, filters.type) &&
        // Archived flags are hidden unless explicitly filtered for, mirroring the API default
        (filters.archived === 'true' ? !!flag.archived : !flag.archived) &&
        (!filters.created_by_id?.length ||
            (flag.created_by != null && filters.created_by_id.includes(flag.created_by.id))) &&
        (!filters.tags?.length || filters.tags.some((tag) => flag.tags?.includes(tag))) &&
        // excluded_tags wins over tags on conflict (AND semantics)
        (!filters.excluded_tags?.length || !filters.excluded_tags.some((tag) => flag.tags?.includes(tag))) &&
        (!filters.evaluation_runtime || flag.evaluation_runtime === filters.evaluation_runtime)
    )
}

export enum FeatureFlagsTab {
    OVERVIEW = 'overview',
    HISTORY = 'history',
    NOTIFICATIONS = 'notifications',
    EXPOSURE = 'exposure',
    Analysis = 'analysis',
    USAGE = 'usage',
    PERMISSIONS = 'permissions',
    PROJECTS = 'projects',
    SCHEDULE = 'schedule',
    FEEDBACK = 'feedback',
    EXPERIMENTS = 'experiments',
    TESTING = 'testing',
}

export interface FeatureFlagsResult extends CountedPaginatedResponse<FeatureFlagType> {
    /* not in the API response */
    filters?: FeatureFlagsFilters | null
    lastUpdatedFlagId?: number | null
}

export interface FeatureFlagsFilters {
    active?: string
    /** 'true' shows only archived flags; when unset, archived flags are excluded */
    archived?: string
    created_by_id?: number[]
    type?: string
    search?: string
    order?: string
    page?: number
    evaluation_runtime?: string
    tags?: string[]
    excluded_tags?: string[]
}

const DEFAULT_FILTERS: FeatureFlagsFilters = {
    active: undefined,
    archived: undefined,
    created_by_id: undefined,
    type: undefined,
    search: undefined,
    order: undefined,
    page: 1,
    evaluation_runtime: undefined,
    tags: undefined,
    excluded_tags: undefined,
}

export interface FlagLogicProps {
    flagPrefix?: string // used to filter flags by prefix e.g. for the user interview flags
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface featureFlagsLogicValues {
    currentProjectId: number | null // projectLogic
    activeTab: FeatureFlagsTab
    breadcrumbs: Breadcrumb[]
    count: number
    displayedFlags: FeatureFlagType[]
    enrichAnalyticsNoticeAcknowledged: boolean
    featureFlags: FeatureFlagsResult
    featureFlagsLoading: boolean
    featureFlagsUpdating: Record<number, boolean>
    filters: FeatureFlagsFilters
    filtersChanged: boolean
    localFlagsCache: FeatureFlagType[]
    pagination: PaginationManual
    paramsFromFilters: {
        active?: string | undefined
        archived?: string | undefined
        created_by_id?: number[] | undefined
        evaluation_runtime?: string | undefined
        excluded_tags?: string[] | undefined
        limit: number
        offset: number
        order?: string | undefined
        page?: number | undefined
        search?: string | undefined
        tags?: string[] | undefined
        type?: string | undefined
    }
    shouldShowEmptyState: boolean
    sidePanelContext: SidePanelSceneContext
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface featureFlagsLogicActions {
    closeEnrichAnalyticsNotice: () => {
        value: true
    }
    deleteFlag: (id: number) => {
        id: number
    }
    loadFeatureFlags: () => any
    loadFeatureFlagsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadFeatureFlagsSuccess: (
        featureFlags: FeatureFlagsResult,
        payload?: any
    ) => {
        featureFlags: FeatureFlagsResult
        payload?: any
    }
    setActiveTab: (tabKey: FeatureFlagsTab) => {
        tabKey: FeatureFlagsTab
    }
    setFeatureFlagUpdating: (
        id: number,
        updating: boolean
    ) => {
        id: number
        updating: boolean
    }
    setFeatureFlagsFilters: (
        filters: Partial<FeatureFlagsFilters>,
        replace?: boolean
    ) => {
        filters: Partial<FeatureFlagsFilters>
        replace: boolean | undefined
    }
    updateFeatureFlag: ({ id, payload }: { id: number; payload: Partial<FeatureFlagType> }) => {
        id: number
        payload: Partial<FeatureFlagType>
    }
    updateFeatureFlagArchived: (payload: { archived: boolean; id: number; via?: FeatureFlagArchivedSource }) => {
        archived: boolean
        id: number
        via?: FeatureFlagArchivedSource | undefined
    }
    updateFeatureFlagArchivedFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    updateFeatureFlagArchivedSuccess: (
        featureFlags: {
            count: number
            filters?: FeatureFlagsFilters | null | undefined
            lastUpdatedFlagId: number
            next?: string | null | undefined
            previous?: string | null | undefined
            results: any[]
        },
        payload?: {
            archived: boolean
            id: number
            via?: FeatureFlagArchivedSource
        }
    ) => {
        featureFlags: {
            count: number
            filters?: FeatureFlagsFilters | null | undefined
            lastUpdatedFlagId: number
            next?: string | null | undefined
            previous?: string | null | undefined
            results: any[]
        }
        payload?: {
            archived: boolean
            id: number
            via?: FeatureFlagArchivedSource | undefined
        }
    }
    updateFeatureFlagFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    updateFeatureFlagSuccess: (
        featureFlags: {
            count: number
            filters?: FeatureFlagsFilters | null | undefined
            lastUpdatedFlagId: number
            next?: string | null | undefined
            previous?: string | null | undefined
            results: any[]
        },
        payload?: {
            id: number
            payload: Partial<FeatureFlagType>
        }
    ) => {
        featureFlags: {
            count: number
            filters?: FeatureFlagsFilters | null | undefined
            lastUpdatedFlagId: number
            next?: string | null | undefined
            previous?: string | null | undefined
            results: any[]
        }
        payload?: {
            id: number
            payload: Partial<FeatureFlagType>
        }
    }
    updateFlag: (flag: FeatureFlagType) => {
        flag: FeatureFlagType
    }
    updateFlagActive: (
        id: number,
        active: boolean
    ) => {
        active: boolean
        id: number
    }
    updateFlagFromPartial: (
        flag: Partial<FeatureFlagType> & {
            id: number
        }
    ) => {
        flag: Partial<FeatureFlagType> & {
            id: number
        }
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface featureFlagsLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        count: (featureFlags: FeatureFlagsResult) => number
        filtersChanged: (filters: FeatureFlagsFilters, featureFlags: FeatureFlagsResult) => boolean
        paramsFromFilters: (filters: FeatureFlagsFilters) => {
            active?: string | undefined
            archived?: string | undefined
            created_by_id?: number[] | undefined
            evaluation_runtime?: string | undefined
            excluded_tags?: string[] | undefined
            limit: number
            offset: number
            order?: string | undefined
            page?: number | undefined
            search?: string | undefined
            tags?: string[] | undefined
            type?: string | undefined
        }
        shouldShowEmptyState: (
            featureFlagsLoading: boolean,
            featureFlags: FeatureFlagsResult,
            filters: FeatureFlagsFilters
        ) => boolean
        pagination: (
            filters: FeatureFlagsFilters,
            displayedFlags: FeatureFlagType[],
            featureFlags: FeatureFlagsResult,
            filtersChanged: boolean
        ) => PaginationManual
        displayedFlags: (localFlagsCache: FeatureFlagType[], filters: FeatureFlagsFilters) => FeatureFlagType[]
    }
}

export type featureFlagsLogicType = MakeLogicType<
    featureFlagsLogicValues,
    featureFlagsLogicActions,
    FlagLogicProps,
    featureFlagsLogicMeta
>

export const featureFlagsLogic = kea<featureFlagsLogicType>([
    props({} as FlagLogicProps),
    path(['scenes', 'feature-flags', 'featureFlagsLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    actions({
        updateFlag: (flag: FeatureFlagType) => ({ flag }),
        updateFlagFromPartial: (flag: Partial<FeatureFlagType> & { id: number }) => ({ flag }),
        updateFlagActive: (id: number, active: boolean) => ({ id, active }),
        deleteFlag: (id: number) => ({ id }),
        setActiveTab: (tabKey: FeatureFlagsTab) => ({ tabKey }),
        setFeatureFlagsFilters: (filters: Partial<FeatureFlagsFilters>, replace?: boolean) => ({ filters, replace }),
        closeEnrichAnalyticsNotice: true,
        setFeatureFlagUpdating: (id: number, updating: boolean) => ({ id, updating }),
    }),
    loaders(({ values }) => ({
        featureFlags: [
            { results: [], count: 0, filters: DEFAULT_FILTERS, offset: 0 } as FeatureFlagsResult,
            {
                loadFeatureFlags: async () => {
                    const response = await api.get(
                        `api/projects/${values.currentProjectId}/feature_flags/?${toParams(values.paramsFromFilters)}`
                    )

                    return {
                        ...response,
                        offset: values.paramsFromFilters.offset,
                        filters: values.filters,
                    }
                },
                updateFeatureFlag: async ({ id, payload }: { id: number; payload: Partial<FeatureFlagType> }) => {
                    try {
                        const response = await api.update(
                            `api/projects/${values.currentProjectId}/feature_flags/${id}`,
                            payload
                        )
                        const updatedFlags = [...values.featureFlags.results].map((flag) =>
                            flag.id === response.id ? response : flag
                        )
                        return { ...values.featureFlags, results: updatedFlags, lastUpdatedFlagId: id }
                    } catch (e: any) {
                        const actionDescription =
                            payload.active === true
                                ? 'enable this feature flag'
                                : payload.active === false
                                  ? 'disable this feature flag'
                                  : 'update this feature flag'
                        handleFlagApprovalRequired(e, id, actionDescription)
                        throw e
                    }
                },
                // Dedicated from updateFeatureFlag so the archive telemetry below can fire only once the
                // archive actually lands, instead of on click (see featureFlagLogic.ts's sibling action).
                updateFeatureFlagArchived: async ({
                    id,
                    archived,
                    via,
                }: {
                    id: number
                    archived: boolean
                    /** Telemetry source; only meaningful (and only captured) when archiving, not unarchiving. */
                    via?: FeatureFlagArchivedSource
                }) => {
                    try {
                        const response = await api.update(
                            `api/projects/${values.currentProjectId}/feature_flags/${id}`,
                            archived ? { archived: true, active: false } : { archived: false }
                        )
                        const updatedFlags = [...values.featureFlags.results].map((flag) =>
                            flag.id === response.id ? response : flag
                        )
                        if (archived && via) {
                            reportFeatureFlagArchived(via)
                        }
                        return { ...values.featureFlags, results: updatedFlags, lastUpdatedFlagId: id }
                    } catch (e: any) {
                        handleFlagApprovalRequired(
                            e,
                            id,
                            archived ? 'archive this feature flag' : 'unarchive this feature flag'
                        )
                        throw e
                    }
                },
            },
        ],
    })),
    reducers({
        featureFlags: {
            updateFlag: (state, { flag }) => ({
                ...state,
                results: state.results.map((stateFlag) => (stateFlag.id === flag.id ? flag : stateFlag)),
            }),
            updateFlagFromPartial: (state, { flag }) => ({
                ...state,
                results: state.results.map((stateFlag) =>
                    stateFlag.id === flag.id ? { ...stateFlag, ...flag } : stateFlag
                ),
            }),
            deleteFlag: (state, { id }) => ({
                ...state,
                count: state.count - 1,
                results: state.results.filter((flag) => flag.id !== id),
            }),
        },
        localFlagsCache: [
            [] as FeatureFlagType[],
            {
                loadFeatureFlagsSuccess: (_, { featureFlags }) => {
                    return featureFlags.results
                },
                updateFeatureFlagSuccess: (_, { featureFlags }) => {
                    return featureFlags.results
                },
                updateFeatureFlagArchivedSuccess: (_, { featureFlags }) => {
                    return featureFlags.results
                },
                updateFlag: (state, { flag }) => state.map((f) => (f.id === flag.id ? flag : f)),
                updateFlagFromPartial: (state, { flag }) =>
                    state.map((f) => (f.id === flag.id ? { ...f, ...flag } : f)),
                deleteFlag: (state, { id }) => state.filter((f) => f.id !== id),
            },
        ],
        activeTab: [
            FeatureFlagsTab.OVERVIEW as FeatureFlagsTab,
            {
                setActiveTab: (state, { tabKey }) =>
                    Object.values<string>(FeatureFlagsTab).includes(tabKey) ? tabKey : state,
            },
        ],
        filters: [
            DEFAULT_FILTERS,
            {
                setFeatureFlagsFilters: (state, { filters, replace }) => {
                    if (replace) {
                        return { ...filters }
                    }
                    return { ...state, ...filters }
                },
            },
        ],
        enrichAnalyticsNoticeAcknowledged: [
            false,
            { persist: true },
            {
                closeEnrichAnalyticsNotice: () => true,
            },
        ],
        featureFlagsUpdating: [
            {} as Record<number, boolean>,
            {
                setFeatureFlagUpdating: (state, { id, updating }) => {
                    if (updating) {
                        return { ...state, [id]: true }
                    }
                    const { [id]: _, ...rest } = state
                    return rest
                },
                updateFeatureFlag: (state, { id }) => ({ ...state, [id]: true }),
                updateFeatureFlagSuccess: (state, { featureFlags }) => {
                    if (featureFlags.lastUpdatedFlagId) {
                        const { [featureFlags.lastUpdatedFlagId]: _, ...rest } = state
                        return rest
                    }
                    return state
                },
                updateFeatureFlagFailure: () => ({}),
                updateFeatureFlagArchived: (state, { id }) => ({ ...state, [id]: true }),
                updateFeatureFlagArchivedSuccess: (state, { featureFlags }) => {
                    if (featureFlags.lastUpdatedFlagId) {
                        const { [featureFlags.lastUpdatedFlagId]: _, ...rest } = state
                        return rest
                    }
                    return state
                },
                updateFeatureFlagArchivedFailure: () => ({}),
            },
        ],
    }),
    selectors({
        count: [(selectors) => [selectors.featureFlags], (featureFlags: FeatureFlagsResult) => featureFlags.count],
        filtersChanged: [
            (s) => [s.filters, s.featureFlags],
            (filters: FeatureFlagsFilters, featureFlags: FeatureFlagsResult): boolean => {
                if (!featureFlags.filters) {
                    return false
                }
                return !objectsEqual({ ...featureFlags.filters, page: undefined }, { ...filters, page: undefined })
            },
        ],
        paramsFromFilters: [
            (s) => [s.filters],
            (filters: FeatureFlagsFilters) => ({
                ...filters,
                limit: FLAGS_PER_PAGE,
                offset: filters.page ? (filters.page - 1) * FLAGS_PER_PAGE : 0,
            }),
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.FeatureFlags,
                    name: 'Feature flags',
                    path: urls.featureFlags(),
                    iconType: 'feature_flag',
                },
            ],
        ],
        // Check to see if any non-default filters are being used
        shouldShowEmptyState: [
            (s) => [s.featureFlagsLoading, s.featureFlags, s.filters],
            (featureFlagsLoading: boolean, featureFlags: FeatureFlagsResult, filters: FeatureFlagsFilters): boolean => {
                return (
                    !featureFlagsLoading && featureFlags.results.length <= 0 && objectsEqual(filters, DEFAULT_FILTERS)
                )
            },
        ],
        pagination: [
            (s) => [s.filters, s.displayedFlags, s.featureFlags, s.filtersChanged],
            (
                filters: FeatureFlagsFilters,
                displayedFlags: FeatureFlagType[],
                featureFlags: FeatureFlagsResult,
                filtersChanged: boolean
            ): PaginationManual => {
                return {
                    controlled: true,
                    pageSize: FLAGS_PER_PAGE,
                    currentPage: filters.page || 1,
                    entryCount: filtersChanged ? displayedFlags.length : featureFlags.count,
                }
            },
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            () => [],
            (): SidePanelSceneContext => ({
                activity_scope: ActivityScope.FEATURE_FLAG,
            }),
        ],
        displayedFlags: [
            (s) => [s.localFlagsCache, s.filters],
            (cache: FeatureFlagType[], filters: FeatureFlagsFilters): FeatureFlagType[] => {
                return cache.filter((flag) => flagMatchesFilters(flag, filters))
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        updateFlagActive: ({ id, active }) => {
            actions.updateFeatureFlag({ id, payload: { active } })
        },
        setFeatureFlagsFilters: async (_, breakpoint) => {
            if (values.activeTab === FeatureFlagsTab.OVERVIEW) {
                await breakpoint(300)
                actions.loadFeatureFlags()
            }
        },
        setActiveTab: () => {
            // Don't carry over pagination from previous tab
            actions.setFeatureFlagsFilters({ page: 1 }, true)
        },
        loadFeatureFlagsSuccess: () => {
            if (values.featureFlags.results.length > 0) {
                globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.CreateFeatureFlag)
            }
        },
    })),
    actionToUrl(({ values }) => {
        const changeUrl = ():
            | [
                  string,
                  Record<string, any>,
                  Record<string, any>,
                  {
                      replace: boolean
                  },
              ]
            | void => {
            const searchParams: Record<string, string | number | string[] | number[]> = {
                ...values.filters,
            }

            let replace = false // set a page in history
            if (!searchParams['tab'] && values.activeTab === FeatureFlagsTab.OVERVIEW) {
                // we are on the overview page, and have clicked the overview tab, don't set history
                replace = true
            }
            searchParams['tab'] = values.activeTab

            // Preserve the activity deep-link param only when on the history tab
            const currentActivity = router.values.searchParams['activity']
            if (currentActivity && values.activeTab === FeatureFlagsTab.HISTORY) {
                searchParams['activity'] = currentActivity
            }

            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace }]
        }

        return {
            setFeatureFlagsFilters: changeUrl,
            setActiveTab: changeUrl,
        }
    }),
    urlToAction(({ actions, values }) => ({
        [urls.featureFlags()]: async (_, searchParams) => {
            const tabInURL = searchParams['tab']

            if (!tabInURL) {
                if (values.activeTab !== FeatureFlagsTab.OVERVIEW) {
                    actions.setActiveTab(FeatureFlagsTab.OVERVIEW)
                }
            } else if (tabInURL !== values.activeTab) {
                actions.setActiveTab(tabInURL)
            }

            const { page, created_by_id, active, archived, type, search, order, evaluation_runtime, tags } =
                searchParams
            const pageFiltersFromUrl: Partial<FeatureFlagsFilters> = {
                created_by_id: parseNumericArrayFilter(created_by_id),
                type,
                order,
                evaluation_runtime,
                tags: parseTagsFilter(tags),
                excluded_tags: parseTagsFilter(searchParams['excluded_tags']),
            }

            pageFiltersFromUrl.active = active !== undefined ? String(active) : undefined
            pageFiltersFromUrl.archived = archived !== undefined ? String(archived) : undefined
            pageFiltersFromUrl.page = page !== undefined ? parseInt(page) : undefined
            pageFiltersFromUrl.search = search !== undefined ? String(search) : undefined

            actions.setFeatureFlagsFilters({ ...DEFAULT_FILTERS, ...pageFiltersFromUrl })
        },
    })),
])
