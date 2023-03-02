import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { promptLogic } from 'lib/logic/promptLogic'
import { getEventNamesForAction, objectsEqual, sum, toParams, uuid } from 'lib/utils'
import posthog from 'posthog-js'
import { eventUsageLogic, InsightEventSource } from 'lib/utils/eventUsageLogic'
import type { insightLogicType } from './insightLogicType'
import {
    ActionType,
    FilterType,
    InsightLogicProps,
    InsightModel,
    InsightShortId,
    InsightType,
    ItemMode,
    SetInsightOptions,
    TrendsFilterType,
    UserType,
} from '~/types'
import { captureTimeToSeeData, currentSessionId } from 'lib/internalMetrics'
import { router } from 'kea-router'
import api, { ApiMethodOptions, getJSONOrThrow } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import {
    filterTrendsClientSideParams,
    isFilterWithHiddenLegendKeys,
    isFunnelsFilter,
    isLifecycleFilter,
    isPathsFilter,
    isRetentionFilter,
    isStickinessFilter,
    isTrendsFilter,
    keyForInsightLogicProps,
} from 'scenes/insights/sharedUtils'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { dashboardsModel } from '~/models/dashboardsModel'
import {
    extractObjectDiffKeys,
    findInsightFromMountedLogic,
    getInsightId,
    getResponseBytes,
    summarizeInsightFilters,
} from './utils'
import { teamLogic } from '../teamLogic'
import { Scene } from 'scenes/sceneTypes'
import { sceneLogic } from 'scenes/sceneLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { urls } from 'scenes/urls'
import { featureFlagLogic, FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { actionsModel } from '~/models/actionsModel'
import * as Sentry from '@sentry/react'
import { DashboardPrivilegeLevel, FEATURE_FLAGS } from 'lib/constants'
import { groupsModel } from '~/models/groupsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { mathsLogic } from 'scenes/trends/mathsLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { TriggerExportProps } from 'lib/components/ExportButton/exporter'
import { parseProperties } from 'lib/components/PropertyFilters/utils'
import { insightsModel } from '~/models/insightsModel'
import { toLocalFilters } from './filters/ActionFilter/entityFilterLogic'
import { loaders } from 'kea-loaders'
import { legacyInsightQuery, queryExportContext } from '~/queries/query'
import { tagsModel } from '~/models/tagsModel'
import { dayjs, now } from 'lib/dayjs'
import { isInsightVizNode } from '~/queries/utils'
import { userLogic } from 'scenes/userLogic'

const IS_TEST_MODE = process.env.NODE_ENV === 'test'
const SHOW_TIMEOUT_MESSAGE_AFTER = 15000
export const UNSAVED_INSIGHT_MIN_REFRESH_INTERVAL_MINUTES = 3

export const defaultFilterTestAccounts = (current_filter_test_accounts: boolean): boolean => {
    // if the current _global_ value is true respect that over any local preference
    return localStorage.getItem('default_filter_test_accounts') === 'true' || current_filter_test_accounts
}

function emptyFilters(filters: Partial<FilterType> | undefined): boolean {
    return (
        !filters ||
        (Object.keys(filters).length < 2 && JSON.stringify(cleanFilters(filters)) === JSON.stringify(cleanFilters({})))
    )
}

export const createEmptyInsight = (
    insightId: InsightShortId | `new-${string}` | 'new',
    filterTestAccounts: boolean
): Partial<InsightModel> => ({
    short_id: insightId !== 'new' && !insightId.startsWith('new-') ? (insightId as InsightShortId) : undefined,
    name: '',
    description: '',
    tags: [],
    filters: filterTestAccounts ? { filter_test_accounts: true } : {},
    result: null,
})

export const insightLogic = kea<insightLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightLogic', key]),

    connect({
        values: [
            teamLogic,
            ['currentTeamId', 'currentTeam'],
            featureFlagLogic,
            ['featureFlags'],
            groupsModel,
            ['aggregationLabel'],
            cohortsModel,
            ['cohortsById'],
            mathsLogic,
            ['mathDefinitions'],
            userLogic,
            ['user'],
        ],
        actions: [tagsModel, ['loadTags']],
        logic: [eventUsageLogic, dashboardsModel, promptLogic({ key: `save-as-insight` })],
    }),

    actions({
        setFilters: (filters: Partial<FilterType>, insightMode?: ItemMode) => ({ filters, insightMode }),
        setFiltersMerge: (filters: Partial<FilterType>) => ({ filters }),
        reportInsightViewedForRecentInsights: () => true,
        reportInsightViewed: (
            insightModel: Partial<InsightModel>,
            filters: Partial<FilterType>,
            previousFilters?: Partial<FilterType>
        ) => ({
            insightModel,
            filters,
            previousFilters,
        }),
        startQuery: (queryId: string) => ({ queryId }),
        endQuery: (payload: {
            queryId: string
            view: InsightType
            scene: Scene | null
            lastRefresh: string | null
            nextAllowedRefresh: string | null
            exception?: Record<string, any>
            response?: { cached: boolean; apiResponseBytes: number; apiUrl: string }
        }) => payload,
        abortQuery: (payload: {
            queryId: string
            view: InsightType
            scene: Scene | null
            exception?: Record<string, any>
        }) => payload,
        markInsightTimedOut: (timedOutQueryId: string | null) => ({ timedOutQueryId }),
        markInsightErrored: (erroredQueryId: string | null) => ({ erroredQueryId }),
        setIsLoading: (isLoading: boolean) => ({ isLoading }),
        setTimeout: (timeout: number | null) => ({ timeout }),
        setLastRefresh: (lastRefresh: string | null) => ({ lastRefresh }),
        setNextAllowedRefresh: (nextAllowedRefresh: string | null) => ({ nextAllowedRefresh }),
        setNotFirstLoad: true,
        setInsight: (insight: Partial<InsightModel>, options: SetInsightOptions) => ({
            insight,
            options,
        }),
        saveAs: true,
        saveAsNamingSuccess: (name: string) => ({ name }),
        cancelChanges: (goToViewMode?: boolean) => ({ goToViewMode }),
        setInsightDescription: (description: string) => ({ description }),
        saveInsight: (redirectToViewMode = true) => ({ redirectToViewMode }),
        saveInsightSuccess: true,
        saveInsightFailure: true,
        fetchedResults: (filters: Partial<FilterType>) => ({ filters }),
        loadInsight: (shortId: InsightShortId) => ({
            shortId,
        }),
        updateInsight: (insight: Partial<InsightModel>, callback?: (insight: Partial<InsightModel>) => void) => ({
            insight,
            callback,
        }),
        loadResults: (refresh = false) => ({ refresh, queryId: uuid() }),
        setInsightMetadata: (metadata: Partial<InsightModel>) => ({ metadata }),
        toggleInsightLegend: true,
        toggleVisibility: (index: number) => ({ index }),
        setHiddenById: (entry: Record<string, boolean | undefined>) => ({ entry }),
        highlightSeries: (seriesIndex: number | null) => ({ seriesIndex }),
        abortAnyRunningQuery: true,
        acknowledgeRefreshButtonChanged: true,
    }),
    loaders(({ actions, cache, values, props }) => ({
        insight: [
            props.cachedInsight ??
                createEmptyInsight(
                    props.dashboardItemId || 'new',
                    values.currentTeam?.test_account_filters_default_checked || false
                ),
            {
                loadInsight: async ({ shortId }) => {
                    const load_query_insight_query_params = !!values.featureFlags[
                        FEATURE_FLAGS.DATA_EXPLORATION_QUERIES_ON_DASHBOARDS
                    ]
                        ? '&include_query_insights=true'
                        : ''
                    const response = await api.get(
                        `api/projects/${teamLogic.values.currentTeamId}/insights/?short_id=${encodeURIComponent(
                            shortId
                        )}${load_query_insight_query_params}`
                    )
                    if (response?.results?.[0]) {
                        return response.results[0]
                    }
                    throw new Error(`Insight "${shortId}" not found`)
                },
                updateInsight: async ({ insight, callback }, breakpoint) => {
                    if (!Object.entries(insight).length) {
                        return values.insight
                    }

                    if ('filters' in insight && !insight.query && emptyFilters(insight.filters)) {
                        const error = new Error('Will not override empty filters in updateInsight.')
                        Sentry.captureException(error, {
                            extra: {
                                filters: JSON.stringify(insight.filters),
                                insight: JSON.stringify(insight),
                                valuesInsight: JSON.stringify(values.insight),
                            },
                        })
                        throw error
                    }

                    const response = await api.update(
                        `api/projects/${teamLogic.values.currentTeamId}/insights/${values.insight.id}`,
                        insight
                    )
                    breakpoint()
                    const updatedInsight: InsightModel = {
                        ...response,
                        result: response.result || values.insight.result,
                    }
                    callback?.(updatedInsight)

                    const removedDashboards = (values.insight.dashboards || []).filter(
                        (d) => !updatedInsight.dashboards?.includes(d)
                    )
                    dashboardsModel.actions.updateDashboardInsight(updatedInsight, removedDashboards)
                    return updatedInsight
                },
                setInsightMetadata: async ({ metadata }, breakpoint) => {
                    const editMode =
                        insightSceneLogic.isMounted() &&
                        insightSceneLogic.values.insight === values.insight &&
                        insightSceneLogic.values.insightMode === ItemMode.Edit

                    if (editMode) {
                        return { ...values.insight, ...metadata }
                    }

                    if (metadata.filters) {
                        const error = new Error(`Will not override filters in setInsightMetadata`)
                        Sentry.captureException(error, {
                            extra: {
                                filters: JSON.stringify(values.insight.filters),
                                insight: JSON.stringify(values.insight),
                            },
                        })
                        throw error
                    }

                    const beforeUpdates = {}
                    for (const key of Object.keys(metadata)) {
                        beforeUpdates[key] = values.savedInsight[key]
                    }

                    const response = await api.update(
                        `api/projects/${teamLogic.values.currentTeamId}/insights/${values.insight.id}`,
                        metadata
                    )
                    breakpoint()

                    // only update the fields that we changed
                    const updatedInsight = { ...values.insight } as InsightModel
                    for (const key of Object.keys(metadata)) {
                        updatedInsight[key] = response[key]
                    }

                    savedInsightsLogic.findMounted()?.actions.loadInsights()
                    dashboardsModel.actions.updateDashboardInsight(updatedInsight)
                    actions.loadTags()

                    lemonToast.success(`Updated insight`, {
                        button: {
                            label: 'Undo',
                            dataAttr: 'edit-insight-undo',
                            action: async () => {
                                const response = await api.update(
                                    `api/projects/${teamLogic.values.currentTeamId}/insights/${values.insight.id}`,
                                    beforeUpdates
                                )
                                // only update the fields that we changed
                                const revertedInsight = { ...values.insight } as InsightModel
                                for (const key of Object.keys(beforeUpdates)) {
                                    revertedInsight[key] = response[key]
                                }
                                savedInsightsLogic.findMounted()?.actions.loadInsights()
                                dashboardsModel.actions.updateDashboardInsight(revertedInsight)
                                actions.setInsight(revertedInsight, { overrideFilter: false, fromPersistentApi: true })
                                lemonToast.success('Insight change reverted')
                            },
                        },
                    })
                    return updatedInsight
                },
                // using values.filters, query for new insight results
                loadResults: async ({ refresh, queryId }, breakpoint) => {
                    // fetch this now, as it might be different when we report below
                    const scene = sceneLogic.isMounted() ? sceneLogic.values.scene : null

                    actions.abortAnyRunningQuery()
                    cache.abortController = new AbortController()
                    const methodOptions: ApiMethodOptions = {
                        signal: cache.abortController.signal,
                    }

                    const { filters } = values

                    const insight = (filters.insight as InsightType | undefined) || InsightType.TRENDS

                    const dashboardItemId = props.dashboardItemId
                    actions.startQuery(queryId)
                    if (dashboardItemId && dashboardsModel.isMounted()) {
                        dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, true, null)
                    }

                    let fetchResponse: any
                    let response: any
                    let apiUrl: string = ''
                    const { currentTeamId } = values

                    if (!currentTeamId) {
                        throw new Error("Can't load insight before current project is determined.")
                    }
                    try {
                        if (
                            values.savedInsight?.id &&
                            objectsEqual(cleanFilters(filters), cleanFilters(values.savedInsight.filters ?? {}))
                        ) {
                            // Instead of making a search for filters, reload the insight via its id if possible.
                            // This makes sure we update the insight's cache key if we get new default filters.
                            apiUrl = `api/projects/${currentTeamId}/insights/${values.savedInsight.id}/?refresh=true`
                            fetchResponse = await api.getResponse(apiUrl, methodOptions)
                        } else {
                            const params = {
                                ...filters,
                                ...(refresh ? { refresh: true } : {}),
                                client_query_id: queryId,
                                session_id: currentSessionId(),
                            }
                            ;[fetchResponse, apiUrl] = await legacyInsightQuery({
                                filters: params,
                                currentTeamId,
                                methodOptions,
                                refresh,
                            })
                        }
                        response = await getJSONOrThrow(fetchResponse)
                    } catch (e: any) {
                        if (e.name === 'AbortError' || e.message?.name === 'AbortError') {
                            actions.abortQuery({
                                queryId,
                                view: insight,
                                scene: scene,
                                exception: e,
                            })
                        }
                        breakpoint()
                        actions.endQuery({
                            queryId,
                            view: insight,
                            scene: scene,
                            lastRefresh: null,
                            nextAllowedRefresh: null,
                            exception: e,
                        })
                        if (dashboardItemId && dashboardsModel.isMounted()) {
                            dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, false, null)
                        }
                        if (isFunnelsFilter(filters)) {
                            eventUsageLogic.actions.reportFunnelCalculated(
                                filters.events?.length || 0,
                                filters.actions?.length || 0,
                                filters.interval || '',
                                filters.funnel_viz_type,
                                false,
                                e.message
                            )
                        }
                        throw e
                    }

                    breakpoint()
                    actions.endQuery({
                        queryId,
                        view: (values.filters.insight as InsightType) || InsightType.TRENDS,
                        scene: scene,
                        lastRefresh: response.last_refresh,
                        nextAllowedRefresh: response.next_allowed_client_refresh,
                        response: {
                            cached: response?.is_cached,
                            apiResponseBytes: getResponseBytes(fetchResponse),
                            apiUrl,
                        },
                    })
                    if (dashboardItemId && dashboardsModel.isMounted()) {
                        dashboardsModel.actions.updateDashboardRefreshStatus(
                            dashboardItemId,
                            false,
                            response.last_refresh
                        )
                    }
                    if (isFunnelsFilter(filters)) {
                        eventUsageLogic.actions.reportFunnelCalculated(
                            filters.events?.length || 0,
                            filters.actions?.length || 0,
                            filters.interval || '',
                            filters.funnel_viz_type,
                            true
                        )
                    }

                    return {
                        ...values.insight,
                        result: response.result,
                        next: response.next,
                        timezone: response.timezone,
                        filters,
                    } as Partial<InsightModel>
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        highlightedSeries: [
            null as number | null,
            {
                highlightSeries: (_, { seriesIndex }) => seriesIndex,
            },
        ],
        insight: {
            loadInsight: (state, { shortId }) =>
                shortId === state.short_id
                    ? state
                    : {
                          // blank slate if switched to a new insight
                          short_id: shortId,
                          tags: [],
                          result: null,
                          filters: {},
                      },
            setInsight: (_state, { insight }) => ({
                ...insight,
            }),
            setInsightMetadata: (state, { metadata }) => ({ ...state, ...metadata }),
            [dashboardsModel.actionTypes.updateDashboardInsight]: (state, { item, extraDashboardIds }) => {
                const targetDashboards = (item?.dashboards || []).concat(extraDashboardIds || [])
                const updateIsForThisDashboard =
                    item?.short_id === state.short_id &&
                    props.dashboardId &&
                    targetDashboards.includes(props.dashboardId)
                if (updateIsForThisDashboard) {
                    return { ...state, ...item }
                } else {
                    return state
                }
            },
            [insightsModel.actionTypes.renameInsightSuccess]: (state, { item }) => {
                if (item.id === state.id) {
                    return { ...state, name: item.name }
                }
                return state
            },
            [insightsModel.actionTypes.insightsAddedToDashboard]: (state, { dashboardId, insightIds }) => {
                if (insightIds.includes(state.id)) {
                    return { ...state, dashboards: [...(state.dashboards || []), dashboardId] }
                } else {
                    return state
                }
            },
            [dashboardsModel.actionTypes.tileRemovedFromDashboard]: (state, { tile, dashboardId }) => {
                if (tile.insight?.id === state.id) {
                    return { ...state, dashboards: state.dashboards?.filter((d) => d !== dashboardId) }
                }
                return state
            },
            [dashboardsModel.actionTypes.deleteDashboardSuccess]: (state, { dashboard }) => {
                const { id } = dashboard
                return { ...state, dashboards: state.dashboards?.filter((d) => d !== id) }
            },
        },
        /* filters contains the in-flight filters, might not (yet?) be the same as insight.filters */
        filters: [
            () => props.cachedInsight?.filters || ({} as Partial<FilterType>),
            {
                setFilters: (state, { filters }) => cleanFilters(filters, state),
                setInsight: (state, { insight: { filters }, options: { overrideFilter } }) =>
                    overrideFilter ? cleanFilters(filters || {}) : state,
                loadInsightSuccess: (state, { insight }) =>
                    Object.keys(state).length === 0 && insight.filters ? insight.filters : state,
                loadResultsSuccess: (state, { insight }) =>
                    Object.keys(state).length === 0 && insight.filters ? insight.filters : state,
            },
        ],
        /** The insight's state as it is in the database. */
        savedInsight: [
            () => props.cachedInsight || ({} as InsightModel),
            {
                setInsight: (state, { insight, options: { fromPersistentApi } }) =>
                    fromPersistentApi ? { ...insight, filters: cleanFilters(insight.filters || {}) } : state,
                loadInsightSuccess: (_, { insight }) => ({ ...insight, filters: cleanFilters(insight.filters || {}) }),
                updateInsightSuccess: (_, { insight }) => ({
                    ...insight,
                    filters: cleanFilters(insight.filters || {}),
                }),
            },
        ],
        timedOutQueryId: [
            null as string | null,
            { markInsightTimedOut: (_, { timedOutQueryId }) => timedOutQueryId, loadResult: () => null },
        ],
        maybeShowTimeoutMessage: [
            false,
            {
                // Only show timeout message if timer is still running
                markInsightTimedOut: (_, { timedOutQueryId }) => !!timedOutQueryId,
                endQuery: (_, { exception }) => !!exception && exception.status !== 500,
                startQuery: () => false,
                loadResult: () => false,
            },
        ],
        erroredQueryId: [
            null as string | null,
            { markInsightErrored: (_, { erroredQueryId }) => erroredQueryId, loadResult: () => null },
        ],
        maybeShowErrorMessage: [
            false,
            {
                endQuery: (_, { exception }) => {
                    const isHTTPErrorStatus = exception?.status >= 400
                    const isBrowserErrorStatus = exception?.status === 0
                    return isHTTPErrorStatus || isBrowserErrorStatus
                },
                loadInsightFailure: (_, { errorObject }) => errorObject?.status === 0,
                loadResultsFailure: (_, { errorObject }) => errorObject?.status === 0,
                startQuery: () => false,
                loadResult: () => false,
            },
        ],
        timeout: [null as number | null, { setTimeout: (_, { timeout }) => timeout }],
        lastRefresh: [
            null as string | null,
            {
                setLastRefresh: (_, { lastRefresh }) => lastRefresh,
                loadInsightSuccess: (_, { insight }) => insight.last_refresh || null,
                loadResult: () => null,
            },
        ],
        nextAllowedRefresh: [
            null as string | null,
            {
                setNextAllowedRefresh: (_, { nextAllowedRefresh }) => nextAllowedRefresh,
                loadInsightSuccess: (_, { insight }) => insight.next_allowed_client_refresh || null,
                loadResult: () => null,
            },
        ],
        insightLoading: [
            false,
            {
                setIsLoading: (_, { isLoading }) => isLoading,
                loadInsight: () => true,
                loadInsightSuccess: () => false,
                loadInsightFailure: () => false,
            },
        ],
        /*
        isFirstLoad determines if this is the first graph being shown after the component is mounted (used for analytics)
        */
        isFirstLoad: [
            true,
            {
                setNotFirstLoad: () => false,
            },
        ],
        queryStartTimes: [
            {} as Record<string, number>,
            {
                startQuery: (state, { queryId }) => ({ ...state, [queryId]: performance.now() }),
            },
        ],
        insightSaving: [
            false,
            {
                saveInsight: () => true,
                saveInsightSuccess: () => false,
                saveInsightFailure: () => false,
            },
        ],
        acknowledgedRefreshButtonChanged: [
            false,
            { persist: true, storageKey: 'acknowledgedRefreshButtonChanged' },
            {
                acknowledgeRefreshButtonChanged: () => true,
            },
        ],
    })),
    selectors({
        /** filters for data that's being displayed, might not be same as `savedInsight.filters` or filters */
        loadedFilters: [(s) => [s.insight], (insight) => insight.filters],
        insightProps: [() => [(_, props) => props], (props): InsightLogicProps => props],
        hasDashboardItemId: [
            () => [(_, props) => props],
            (props: InsightLogicProps) =>
                !!props.dashboardItemId && props.dashboardItemId !== 'new' && !props.dashboardItemId.startsWith('new-'),
        ],
        derivedName: [
            (s) => [s.insight, s.aggregationLabel, s.cohortsById, s.mathDefinitions],
            (insight, aggregationLabel, cohortsById, mathDefinitions) =>
                summarizeInsightFilters(insight.filters || {}, aggregationLabel, cohortsById, mathDefinitions).slice(
                    0,
                    400
                ),
        ],
        insightName: [(s) => [s.insight, s.derivedName], (insight, derivedName) => insight.name || derivedName],
        insightId: [(s) => [s.insight], (insight) => insight?.id || null],
        isFilterBasedInsight: [
            (s) => [s.insight],
            (insight) => Object.keys(insight.filters || {}).length > 0 && !insight.query,
        ],
        isQueryBasedInsight: [(s) => [s.insight], (insight) => !!insight.query],
        isInsightVizQuery: [(s) => [s.insight], (insight) => isInsightVizNode(insight.query)],
        canEditInsight: [
            (s) => [s.insight],
            (insight) =>
                insight.effective_privilege_level == undefined ||
                insight.effective_privilege_level >= DashboardPrivilegeLevel.CanEdit,
        ],
        insightChanged: [
            (s) => [s.insight, s.savedInsight, s.filters],
            (insight, savedInsight, filters): boolean =>
                (insight.name || '') !== (savedInsight.name || '') ||
                (insight.description || '') !== (savedInsight.description || '') ||
                !objectsEqual(insight.tags || [], savedInsight.tags || []) ||
                !objectsEqual(cleanFilters(savedInsight.filters || {}), cleanFilters(filters || {})),
        ],
        isInDashboardContext: [
            () => [router.selectors.location],
            ({ pathname }) =>
                pathname.startsWith('/dashboard') ||
                pathname.startsWith('/home') ||
                pathname.startsWith('/shared-dashboard'),
        ],
        allEventNames: [
            (s) => [s.filters, actionsModel.selectors.actions],
            (filters, actions: ActionType[]) => {
                const allEvents = [
                    ...(filters.events || []).map((e) => String(e.id)),
                    ...(filters.actions || []).flatMap((action) => getEventNamesForAction(action.id, actions)),
                ]
                // remove duplicates and empty events
                return Array.from(new Set(allEvents.filter((a): a is string => !!a)))
            },
        ],
        hiddenLegendKeys: [
            (s) => [s.filters],
            (filters) => {
                const hiddenLegendKeys: TrendsFilterType['hidden_legend_keys'] = {}
                if (isFilterWithHiddenLegendKeys(filters) && filters.hidden_legend_keys) {
                    for (const [key, value] of Object.entries(filters.hidden_legend_keys)) {
                        // Transform pre-#12113 funnel series keys to the current more reliable format.
                        // Old: `${step.type}/${step.action_id}/${step.order}/${breakdownValues.join('_')}`
                        // New: breakdownValues.join('::')
                        // If you squint you'll notice this doesn't actually handle the .join() part, but that's fine,
                        // because that's only relevant for funnels with multiple breakdowns, and that hasn't been
                        // released to users at the point of the format change.
                        const oldFormatMatch = key.match(/\w+\/.+\/\d+\/(.+)/)
                        if (oldFormatMatch) {
                            // Don't override values for series if already set from a previously-seen old-format key
                            if (!(oldFormatMatch[1] in hiddenLegendKeys)) {
                                hiddenLegendKeys[oldFormatMatch[1]] = value
                            }
                        } else {
                            hiddenLegendKeys[key] = value
                        }
                    }
                }
                return hiddenLegendKeys
            },
        ],
        filtersKnown: [
            (s) => [s.insight],
            ({ filters }) => {
                // any real filter will have the `insight` key in it
                return 'insight' in (filters ?? {})
            },
        ],
        filterPropertiesCount: [
            (s) => [s.filters],
            (filters): number => {
                return Array.isArray(filters.properties)
                    ? filters.properties.length
                    : sum(filters.properties?.values?.map((x) => x.values.length) || [])
            },
        ],
        localFilters: [
            (s) => [s.filters],
            (filters) => {
                return toLocalFilters(filters)
            },
        ],
        isSingleSeries: [
            (s) => [s.filters, s.localFilters],
            (filters, localFilters): boolean => {
                return (isTrendsFilter(filters) && !!filters.formula) || localFilters.length <= 1
            },
        ],
        intervalUnit: [(s) => [s.filters], (filters) => filters?.interval || 'day'],
        timezone: [(s) => [s.insight], (insight) => insight?.timezone || 'UTC'],
        exporterResourceParams: [
            (s) => [s.filters, s.currentTeamId, s.insight],
            (
                filters: Partial<FilterType>,
                currentTeamId: number,
                insight: Partial<InsightModel>
            ): TriggerExportProps['export_context'] | null => {
                const params = { ...filters }

                const filename = ['export', insight.name || insight.derived_name].join('-')

                if (!!insight.query) {
                    return { ...queryExportContext(insight.query), filename }
                } else {
                    if (isTrendsFilter(filters) || isStickinessFilter(filters) || isLifecycleFilter(filters)) {
                        return {
                            path: `api/projects/${currentTeamId}/insights/trend/?${toParams(
                                filterTrendsClientSideParams(params)
                            )}`,
                            filename,
                        }
                    } else if (isRetentionFilter(filters)) {
                        return {
                            filename,
                            path: `api/projects/${currentTeamId}/insights/retention/?${toParams(params)}`,
                        }
                    } else if (isFunnelsFilter(filters)) {
                        return {
                            filename,
                            method: 'POST',
                            path: `api/projects/${currentTeamId}/insights/funnel`,
                            body: params,
                        }
                    } else if (isPathsFilter(filters)) {
                        return {
                            filename,
                            method: 'POST',
                            path: `api/projects/${currentTeamId}/insights/path`,
                            body: params,
                        }
                    } else {
                        return null
                    }
                }
            },
        ],
        isUsingSessionAnalysis: [
            (s) => [s.filters],
            (filters: Partial<FilterType>): boolean => {
                const entities = (filters.events || []).concat(filters.actions ?? [])
                const using_session_breakdown = filters.breakdown_type === 'session'
                const using_session_math = entities.some((entity) => entity.math === 'unique_session')
                const using_session_property_math = entities.some((entity) => {
                    // Should be made more generic is we ever add more session properties
                    return entity.math_property === '$session_duration'
                })
                const using_entity_session_property_filter = entities.some((entity) => {
                    return parseProperties(entity.properties).some((property) => property.type === 'session')
                })
                const using_global_session_property_filter = parseProperties(filters.properties).some(
                    (property) => property.type === 'session'
                )
                return (
                    using_session_breakdown ||
                    using_session_math ||
                    using_session_property_math ||
                    using_entity_session_property_filter ||
                    using_global_session_property_filter
                )
            },
        ],
        isUsingDataExploration: [
            (s) => [s.featureFlags],
            (featureFlags: FeatureFlagsSet): boolean => {
                return !!featureFlags[FEATURE_FLAGS.DATA_EXPLORATION_INSIGHTS]
            },
        ],
        displayRefreshButtonChangedNotice: [
            (s) => [s.acknowledgedRefreshButtonChanged, s.user],
            (acknowledgedRefreshButtonChanged: boolean, user: UserType): boolean => {
                return dayjs(user.date_joined).isBefore('2023-02-13') && !acknowledgedRefreshButtonChanged
            },
        ],
        insightRefreshButtonDisabledReason: [
            (s) => [s.nextAllowedRefresh, s.lastRefresh],
            (nextAllowedRefresh: string | null, lastRefresh: string | null): string => {
                let disabledReason = ''

                if (!!nextAllowedRefresh && now().isBefore(dayjs(nextAllowedRefresh))) {
                    // If this is a saved insight, the result will contain nextAllowedRefresh and we use that to disable the button
                    disabledReason = `You can refresh this insight again ${dayjs(nextAllowedRefresh).fromNow()}`
                } else if (
                    !!lastRefresh &&
                    now()
                        .subtract(UNSAVED_INSIGHT_MIN_REFRESH_INTERVAL_MINUTES - 0.5, 'minutes')
                        .isBefore(lastRefresh)
                ) {
                    // Unsaved insights don't get cached and get refreshed on every page load, but we avoid allowing users to click
                    // 'refresh' more than once every UNSAVED_INSIGHT_MIN_REFRESH_INTERVAL_MINUTES. This can be bypassed by simply
                    // refreshing the page though, as there's no cache layer on the backend
                    disabledReason = `You can refresh this insight again ${dayjs(lastRefresh)
                        .add(UNSAVED_INSIGHT_MIN_REFRESH_INTERVAL_MINUTES, 'minutes')
                        .fromNow()}`
                }

                return disabledReason
            },
        ],
    }),
    listeners(({ actions, selectors, values, cache }) => ({
        setFiltersMerge: ({ filters }) => {
            actions.setFilters({ ...values.filters, ...filters })
        },
        setFilters: async ({ filters }, _, __, previousState) => {
            const previousFilters = selectors.filters(previousState)
            if (objectsEqual(previousFilters, filters)) {
                return
            }
            const dupeFilters = { ...filters }
            const dupePrevFilters = { ...selectors.filters(previousState) }
            if ('new_entity' in dupeFilters) {
                delete (dupeFilters as any).new_entity
            }
            if ('new_entity' in dupePrevFilters) {
                delete (dupePrevFilters as any).new_entity
            }
            if (objectsEqual(dupePrevFilters, dupeFilters)) {
                return
            }

            actions.reportInsightViewed(values.insight, filters, previousFilters)

            const backendFilterChanged = !objectsEqual(
                Object.assign({}, values.filters, {
                    layout: undefined,
                    hidden_legend_keys: undefined,
                    funnel_advanced: undefined,
                    show_legend: undefined,
                }),
                Object.assign({}, values.loadedFilters, {
                    layout: undefined,
                    hidden_legend_keys: undefined,
                    funnel_advanced: undefined,
                    show_legend: undefined,
                })
            )

            // (Re)load results when filters have changed or if there's no result yet
            if (backendFilterChanged || !values.insight?.result) {
                if (!values.isUsingDataExploration && !values.insight?.query) {
                    actions.loadResults()
                }
            }
        },
        reportInsightViewedForRecentInsights: async () => {
            // Report the insight being viewed to our '/viewed' endpoint. Used for "recently viewed insights"

            // TODO: This should be merged into the same action as `reportInsightViewed`, but we can't right now
            // because there are some issues with `reportInsightViewed` not being called when the
            // insightLogic is already loaded.
            // For example, if the user navigates to an insight after viewing it on a dashboard, `reportInsightViewed`
            // will not be called. This should be fixed when we refactor insightLogic, but the logic is a bit tangled
            // right now
            if (values.insight.id) {
                return api.create(`api/projects/${teamLogic.values.currentTeamId}/insights/${values.insight.id}/viewed`)
            }
        },
        reportInsightViewed: async ({ filters, previousFilters }, breakpoint) => {
            await breakpoint(IS_TEST_MODE ? 1 : 500) // Debounce to avoid noisy events from changing filters multiple times
            if (!values.isInDashboardContext) {
                const { fromDashboard } = router.values.hashParams
                const changedKeysObj: Record<string, any> | undefined =
                    previousFilters && extractObjectDiffKeys(previousFilters, filters)

                const insightMode =
                    insightSceneLogic.isMounted() && insightSceneLogic.values.insight === values.insight
                        ? insightSceneLogic.values.insightMode
                        : ItemMode.View

                eventUsageLogic.actions.reportInsightViewed(
                    values.insight,
                    filters || {},
                    insightMode,
                    values.isFirstLoad,
                    Boolean(fromDashboard),
                    0,
                    changedKeysObj,
                    values.isUsingSessionAnalysis
                )

                actions.setNotFirstLoad()
                await breakpoint(IS_TEST_MODE ? 1 : 10000) // Tests will wait for all breakpoints to finish

                eventUsageLogic.actions.reportInsightViewed(
                    values.insight,
                    filters || {},
                    insightMode,
                    values.isFirstLoad,
                    Boolean(fromDashboard),
                    10,
                    changedKeysObj,
                    values.isUsingSessionAnalysis
                )
            }
        },
        startQuery: ({ queryId }) => {
            actions.markInsightTimedOut(null)
            actions.markInsightErrored(null)
            values.timeout && clearTimeout(values.timeout || undefined)
            const view = values.filters.insight
            actions.setTimeout(
                window.setTimeout(() => {
                    try {
                        if (values && view == values.filters.insight) {
                            actions.markInsightTimedOut(queryId)
                            const tags = {
                                insight: values.filters.insight,
                                scene: sceneLogic.isMounted() ? sceneLogic.values.scene : null,
                            }
                            posthog.capture('insight timeout message shown', tags)
                        }
                    } catch (e) {
                        console.warn('Error setting insight timeout', e)
                    }
                }, SHOW_TIMEOUT_MESSAGE_AFTER)
            )
            actions.setIsLoading(true)
        },
        abortAnyRunningQuery: () => {
            if (cache.abortController) {
                cache.abortController.abort()
                cache.abortController = null
            }
        },
        abortQuery: async ({ queryId }) => {
            try {
                const { currentTeamId } = values

                await api.create(`api/projects/${currentTeamId}/insights/cancel`, { client_query_id: queryId })

                const duration = performance.now() - values.queryStartTimes[queryId]
                await captureTimeToSeeData(values.currentTeamId, {
                    type: 'insight_load',
                    context: 'insight',
                    primary_interaction_id: queryId,
                    query_id: queryId,
                    status: 'cancelled',
                    time_to_see_data_ms: Math.floor(duration),
                    insights_fetched: 0,
                    insights_fetched_cached: 0,
                    api_response_bytes: 0,
                    insight: values.filters.insight,
                })
            } catch (e) {
                console.warn('Failed cancelling query', e)
            }
        },
        endQuery: ({ queryId, view, lastRefresh, scene, exception, response, nextAllowedRefresh }) => {
            if (values.timeout) {
                clearTimeout(values.timeout)
            }
            if (view === values.filters.insight && values.currentTeamId) {
                actions.markInsightTimedOut(values.maybeShowTimeoutMessage ? queryId : null)
                actions.markInsightErrored(values.maybeShowErrorMessage ? queryId : null)
                actions.setLastRefresh(lastRefresh || null)
                actions.setNextAllowedRefresh(nextAllowedRefresh || null)
                actions.setIsLoading(false)

                const duration = performance.now() - values.queryStartTimes[queryId]
                const tags = {
                    insight: values.filters.insight,
                    scene: sceneLogic.isMounted() ? sceneLogic.values.scene : scene,
                    success: !exception,
                    ...exception,
                }

                posthog.capture('insight loaded', { ...tags, duration })

                captureTimeToSeeData(values.currentTeamId, {
                    type: 'insight_load',
                    context: 'insight',
                    primary_interaction_id: queryId,
                    query_id: queryId,
                    status: exception ? 'failure' : 'success',
                    time_to_see_data_ms: Math.floor(duration),
                    insights_fetched: 1,
                    insights_fetched_cached: response?.cached ? 1 : 0,
                    api_response_bytes: response?.apiResponseBytes,
                    api_url: response?.apiUrl,
                    insight: values.filters.insight,
                    is_primary_interaction: true,
                })
                if (values.maybeShowErrorMessage) {
                    posthog.capture('insight error message shown', { ...tags, duration })
                }
            }
        },
        loadResult: () => {
            if (values.timeout) {
                clearTimeout(values.timeout)
            }
        },
        saveInsight: async ({ redirectToViewMode }) => {
            const insightNumericId =
                values.insight.id || (values.insight.short_id ? await getInsightId(values.insight.short_id) : undefined)
            const { name, description, favorited, filters, query, deleted, dashboards, tags } = values.insight
            let savedInsight: InsightModel

            try {
                // We don't want to send ALL the insight properties back to the API, so only grabbing fields that might have changed
                const insightRequest: Partial<InsightModel> = {
                    name,
                    derived_name: values.derivedName,
                    description,
                    favorited,
                    filters,
                    query,
                    deleted,
                    saved: true,
                    dashboards,
                    tags,
                }

                savedInsight = insightNumericId
                    ? await api.update(
                          `api/projects/${teamLogic.values.currentTeamId}/insights/${insightNumericId}`,
                          insightRequest
                      )
                    : await api.create(`api/projects/${teamLogic.values.currentTeamId}/insights/`, insightRequest)
                actions.saveInsightSuccess()
            } catch (e) {
                actions.saveInsightFailure()
                throw e
            }

            actions.setInsight(
                { ...savedInsight, result: savedInsight.result || values.insight.result },
                { fromPersistentApi: true, overrideFilter: true }
            )
            eventUsageLogic.actions.reportInsightSaved(filters || {}, insightNumericId === undefined)
            lemonToast.success(`Insight saved${dashboards?.length === 1 ? ' & added to dashboard' : ''}`, {
                button: {
                    label: 'View Insights list',
                    action: () => router.actions.push(urls.savedInsights()),
                },
            })

            dashboardsModel.actions.updateDashboardInsight(savedInsight)

            const mountedInsightSceneLogic = insightSceneLogic.findMounted()
            if (redirectToViewMode) {
                if (!insightNumericId && dashboards?.length === 1) {
                    // redirect new insights added to dashboard to the dashboard
                    router.actions.push(urls.dashboard(dashboards[0], savedInsight.short_id))
                } else if (insightNumericId) {
                    mountedInsightSceneLogic?.actions.setInsightMode(ItemMode.View, InsightEventSource.InsightHeader)
                } else {
                    router.actions.push(urls.insightView(savedInsight.short_id))
                }
            } else if (!insightNumericId) {
                // If we've just saved a new insight without redirecting to view mode, we need to redirect to edit mode
                // so that we aren't stuck on /insights/new
                router.actions.push(urls.insightEdit(savedInsight.short_id))
            }
        },
        saveAs: async () => {
            promptLogic({ key: `save-as-insight` }).actions.prompt({
                title: 'Save as new insight',
                placeholder: 'Please enter the new name',
                value: `${values.insight.name || values.insight.derived_name} (copy)`,
                error: 'You must enter a name',
                success: actions.saveAsNamingSuccess,
            })
        },
        saveAsNamingSuccess: async ({ name }) => {
            const insight: InsightModel = await api.create(`api/projects/${teamLogic.values.currentTeamId}/insights/`, {
                name,
                filters: values.filters,
                saved: true,
            })
            lemonToast.info(`You're now working on a copy of ${values.insight.name ?? values.insight.derived_name}`)
            actions.setInsight(insight, { fromPersistentApi: true, overrideFilter: true })
            savedInsightsLogic.findMounted()?.actions.loadInsights()
            router.actions.push(urls.insightEdit(insight.short_id))
        },
        loadInsightSuccess: async ({ insight }) => {
            actions.reportInsightViewed(insight, insight?.filters || {})
            // loaded `/api/projects/:id/insights`, but it didn't have `results`, so make another query
            if (!insight.result && !insight.query && values.filters) {
                actions.loadResults()
            }
        },
        toggleInsightLegend: () => {
            const newFilters: Partial<TrendsFilterType> = {
                ...values.filters,
                show_legend: !(values.filters as Partial<TrendsFilterType>).show_legend,
            }
            actions.setFilters(newFilters)
        },
        toggleVisibility: ({ index }) => {
            const currentIsHidden = !!values.hiddenLegendKeys?.[index]
            const newFilters: Partial<TrendsFilterType> = {
                ...values.filters,
                hidden_legend_keys: {
                    ...values.hiddenLegendKeys,
                    [`${index}`]: currentIsHidden ? undefined : true,
                },
            }
            actions.setFilters(newFilters)
        },
        setHiddenById: ({ entry }) => {
            const nextEntries = Object.fromEntries(
                Object.entries(entry).map(([index, hiddenState]) => [index, hiddenState ? true : undefined])
            )
            const newFilters: Partial<TrendsFilterType> = {
                ...values.filters,
                hidden_legend_keys: {
                    ...values.hiddenLegendKeys,
                    ...nextEntries,
                },
            }
            actions.setFilters(newFilters)
        },
        cancelChanges: ({ goToViewMode }) => {
            actions.setFilters(values.savedInsight.filters || {})
            if (goToViewMode) {
                insightSceneLogic.findMounted()?.actions.setInsightMode(ItemMode.View, InsightEventSource.InsightHeader)
                eventUsageLogic.actions.reportInsightsTabReset()
            }
        },
        acknowledgeRefreshButtonChanged: () => {
            localStorage.setItem('acknowledged_refresh_button_changed', 'true')
        },
    })),
    events(({ props, values, actions }) => ({
        afterMount: () => {
            const hasDashboardItemId =
                !!props.dashboardItemId && props.dashboardItemId !== 'new' && !props.dashboardItemId.startsWith('new-')
            const isCachedWithResultAndFilters =
                !!props.cachedInsight && !!props.cachedInsight?.result && !!props.cachedInsight?.filters

            if (!isCachedWithResultAndFilters) {
                if (hasDashboardItemId) {
                    const insight = findInsightFromMountedLogic(
                        props.dashboardItemId as string | InsightShortId,
                        props.dashboardId
                    )
                    if (insight) {
                        actions.setInsight(insight, { overrideFilter: true, fromPersistentApi: true })
                        if (insight?.result) {
                            actions.reportInsightViewed(insight, insight.filters || {})
                        } else if (!insight.query) {
                            actions.loadResults()
                        }
                        return
                    }
                }
                if (!props.doNotLoad) {
                    if (props.cachedInsight?.filters && !props.cachedInsight?.query) {
                        actions.loadResults()
                    } else if (hasDashboardItemId) {
                        actions.loadInsight(props.dashboardItemId as InsightShortId)
                    }
                }
            }
        },
        beforeUnmount: () => {
            if (values.timeout) {
                clearTimeout(values.timeout)
            }
        },
    })),
])
