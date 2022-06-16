import { kea } from 'kea'
import { prompt } from 'lib/logic/prompt'
import { getEventNamesForAction, objectsEqual, sum, toParams, uuid } from 'lib/utils'
import posthog from 'posthog-js'
import { eventUsageLogic, InsightEventSource } from 'lib/utils/eventUsageLogic'
import type { insightLogicType } from './insightLogicType'
import {
    ActionType,
    FilterType,
    DashboardTile,
    InsightLogicProps,
    InsightModel,
    InsightShortId,
    InsightType,
    ItemMode,
    SetInsightOptions,
} from '~/types'
import { captureInternalMetric } from 'lib/internalMetrics'
import { router } from 'kea-router'
import api from 'lib/api'
import { lemonToast } from 'lib/components/lemonToast'
import { filterTrendsClientSideParams, keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { dashboardsModel } from '~/models/dashboardsModel'
import { pollFunnel } from 'scenes/funnels/funnelUtils'
import { extractObjectDiffKeys, findInsightFromMountedLogic, getInsightId, summarizeInsightFilters } from './utils'
import { teamLogic } from '../teamLogic'
import { Scene } from 'scenes/sceneTypes'
import { sceneLogic } from 'scenes/sceneLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { urls } from 'scenes/urls'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { actionsModel } from '~/models/actionsModel'
import * as Sentry from '@sentry/react'
import { DashboardPrivilegeLevel } from 'lib/constants'
import { groupsModel } from '~/models/groupsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { mathsLogic } from 'scenes/trends/mathsLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { mergeWithDashboardTile } from 'scenes/insights/utils/dashboardTiles'

const IS_TEST_MODE = process.env.NODE_ENV === 'test'
const SHOW_TIMEOUT_MESSAGE_AFTER = 15000

export const defaultFilterTestAccounts = (): boolean => {
    return localStorage.getItem('default_filter_test_accounts') === 'true' || false
}

function emptyFilters(filters: Partial<FilterType> | undefined): boolean {
    return (
        !filters ||
        (Object.keys(filters).length < 2 && JSON.stringify(cleanFilters(filters)) === JSON.stringify(cleanFilters({})))
    )
}

export const createEmptyInsight = (insightId: InsightShortId | `new-${string}` | 'new'): Partial<InsightModel> => ({
    short_id: insightId !== 'new' && !insightId.startsWith('new-') ? (insightId as InsightShortId) : undefined,
    name: '',
    description: '',
    tags: [],
    filters: {},
    result: null,
})

export const insightLogic = kea<insightLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('new'),
    path: (key) => ['scenes', 'insights', 'insightLogic', key],

    connect: {
        values: [
            teamLogic,
            ['currentTeamId'],
            featureFlagLogic,
            ['featureFlags'],
            groupsModel,
            ['aggregationLabel'],
            cohortsModel,
            ['cohortsById'],
            mathsLogic,
            ['mathDefinitions'],
        ],
        logic: [eventUsageLogic, dashboardsModel, prompt({ key: `save-as-insight` })],
    },

    actions: () => ({
        setActiveView: (type: InsightType) => ({ type }),
        updateActiveView: (type: InsightType) => ({ type }),
        setFilters: (filters: Partial<FilterType>, insightMode?: ItemMode) => ({ filters, insightMode }),
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
        endQuery: (
            queryId: string,
            view: InsightType,
            lastRefresh: string | null,
            exception?: Record<string, any>
        ) => ({
            queryId,
            view,
            lastRefresh,
            exception,
        }),
        abortQuery: (queryId: string, view: InsightType, scene: Scene | null, exception?: Record<string, any>) => ({
            queryId,
            view,
            scene,
            exception,
        }),
        setShowTimeoutMessage: (showTimeoutMessage: boolean) => ({ showTimeoutMessage }),
        setShowErrorMessage: (showErrorMessage: boolean) => ({ showErrorMessage }),
        setIsLoading: (isLoading: boolean) => ({ isLoading }),
        setTimeout: (timeout: number | null) => ({ timeout }),
        setLastRefresh: (lastRefresh: string | null) => ({ lastRefresh }),
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
        setTagLoading: (tagLoading: boolean) => ({ tagLoading }),
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
    }),
    loaders: ({ actions, cache, values, props }) => ({
        insight: [
            props.cachedInsight ?? createEmptyInsight(props.dashboardItemId || 'new'),
            {
                loadInsight: async ({ shortId }) => {
                    const response = await api.get(
                        `api/projects/${teamLogic.values.currentTeamId}/insights/?short_id=${encodeURIComponent(
                            shortId
                        )}`
                    )
                    if (response?.results?.[0]) {
                        return response.results[0]
                    }
                    lemonToast.error(`Insight "${shortId}" not found`)
                    throw new Error(`Insight "${shortId}" not found`)
                },
                updateInsight: async ({ insight, callback }, breakpoint) => {
                    if (!Object.entries(insight).length) {
                        return values.insight
                    }

                    if ('filters' in insight && emptyFilters(insight.filters)) {
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

                    savedInsightsLogic.findMounted()?.actions.loadInsights()
                    for (const id of updatedInsight.dashboards ?? []) {
                        dashboardLogic.findMounted({ id })?.actions.loadDashboardItems()
                    }
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
                    dashboardsModel.actions.updateDashboardItem(updatedInsight)
                    return updatedInsight
                },
                // using values.filters, query for new insight results
                loadResults: async ({ refresh, queryId }, breakpoint) => {
                    // fetch this now, as it might be different when we report below
                    const scene = sceneLogic.isMounted() ? sceneLogic.values.scene : null

                    // If a query is in progress, debounce before making the second query
                    if (cache.abortController) {
                        await breakpoint(300)
                        cache.abortController.abort()
                    }
                    cache.abortController = new AbortController()

                    const { filters } = values
                    const insight = (filters.insight as InsightType | undefined) || InsightType.TRENDS
                    const params = { ...filters, ...(refresh ? { refresh: true } : {}) }

                    const dashboardItemId = props.dashboardItemId
                    actions.startQuery(queryId)
                    if (dashboardItemId && dashboardsModel.isMounted()) {
                        dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, true, null)
                    }

                    let response
                    const { currentTeamId } = values
                    if (!currentTeamId) {
                        throw new Error("Can't load insight before current project is determined.")
                    }
                    try {
                        if (
                            insight === InsightType.TRENDS ||
                            insight === InsightType.STICKINESS ||
                            insight === InsightType.LIFECYCLE
                        ) {
                            response = await api.get(
                                `api/projects/${currentTeamId}/insights/trend/?${toParams(
                                    filterTrendsClientSideParams(params)
                                )}`,
                                cache.abortController.signal
                            )
                        } else if (insight === InsightType.RETENTION) {
                            response = await api.get(
                                `api/projects/${currentTeamId}/insights/retention/?${toParams(params)}`,
                                cache.abortController.signal
                            )
                        } else if (insight === InsightType.FUNNELS) {
                            const { new_entity, ...restParams } = params
                            if (new_entity && new_entity.length > 0) {
                                return
                            }
                            response = await pollFunnel(currentTeamId, restParams)
                        } else if (insight === InsightType.PATHS) {
                            response = await api.create(`api/projects/${currentTeamId}/insights/path`, params)
                        } else {
                            throw new Error(`Cannot load insight of type ${insight}`)
                        }
                    } catch (e: any) {
                        if (e.name === 'AbortError') {
                            actions.abortQuery(queryId, insight, scene, e)
                        }
                        breakpoint()
                        cache.abortController = null
                        actions.endQuery(queryId, insight, null, e)
                        if (dashboardItemId && dashboardsModel.isMounted()) {
                            dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, false, null)
                        }
                        if (filters.insight === InsightType.FUNNELS) {
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
                    cache.abortController = null
                    actions.endQuery(
                        queryId,
                        (values.filters.insight as InsightType) || InsightType.TRENDS,
                        response.last_refresh
                    )
                    if (dashboardItemId && dashboardsModel.isMounted()) {
                        dashboardsModel.actions.updateDashboardRefreshStatus(
                            dashboardItemId,
                            false,
                            response.last_refresh
                        )
                    }
                    if (filters.insight === InsightType.FUNNELS) {
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
    }),
    reducers: ({ props }) => ({
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
            [dashboardsModel.actionTypes.updateDashboardItem]: (state, { item, dashboardIds }) => {
                if (item.short_id !== state.short_id) {
                    return state
                }

                const updateIsForThisDashboard = props.dashboardId && (dashboardIds || []).includes(props.dashboardId)
                if (updateIsForThisDashboard) {
                    return { ...item }
                } else {
                    return mergeWithDashboardTile(item, state as DashboardTile)
                }
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
        showTimeoutMessage: [false, { setShowTimeoutMessage: (_, { showTimeoutMessage }) => showTimeoutMessage }],
        maybeShowTimeoutMessage: [
            false,
            {
                // Only show timeout message if timer is still running
                setShowTimeoutMessage: (_, { showTimeoutMessage }) => showTimeoutMessage,
                endQuery: (_, { exception }) => !!exception && exception.status !== 500,
                startQuery: () => false,
                setActiveView: () => false,
            },
        ],
        showErrorMessage: [false, { setShowErrorMessage: (_, { showErrorMessage }) => showErrorMessage }],
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
                setActiveView: () => false,
            },
        ],
        timeout: [null as number | null, { setTimeout: (_, { timeout }) => timeout }],
        lastRefresh: [
            null as string | null,
            {
                setLastRefresh: (_, { lastRefresh }) => lastRefresh,
                loadInsightSuccess: (_, { insight }) => insight.last_refresh || null,
                setActiveView: () => null,
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
                startQuery: (state, { queryId }) => ({ ...state, [queryId]: new Date().getTime() }),
            },
        ],
        tagLoading: [
            false,
            {
                setTagLoading: (_, { tagLoading }) => tagLoading,
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
    }),
    selectors: {
        /** filters for data that's being displayed, might not be same as `savedInsight.filters` or filters */
        loadedFilters: [(s) => [s.insight], (insight) => insight.filters],
        insightProps: [() => [(_, props) => props], (props): InsightLogicProps => props],
        derivedName: [
            (s) => [s.insight, s.aggregationLabel, s.cohortsById, s.mathDefinitions],
            (insight, aggregationLabel, cohortsById, mathDefinitions) =>
                summarizeInsightFilters(insight.filters || {}, aggregationLabel, cohortsById, mathDefinitions).slice(
                    0,
                    400
                ),
        ],
        insightName: [(s) => [s.insight, s.derivedName], (insight, derivedName) => insight.name || derivedName],
        canEditInsight: [
            (s) => [s.insight],
            (insight) =>
                insight.effective_privilege_level == undefined ||
                insight.effective_privilege_level >= DashboardPrivilegeLevel.CanEdit,
        ],
        activeView: [(s) => [s.filters], (filters) => filters.insight || InsightType.TRENDS],
        loadedView: [
            (s) => [s.insight, s.activeView],
            ({ filters }, activeView) => filters?.insight || activeView || InsightType.TRENDS,
        ],
        insightChanged: [
            (s) => [s.insight, s.savedInsight, s.filters],
            (insight, savedInsight, filters): boolean =>
                (insight.name || '') !== (savedInsight.name || '') ||
                (insight.description || '') !== (savedInsight.description || '') ||
                !objectsEqual(insight.tags || [], savedInsight.tags || []) ||
                !objectsEqual(cleanFilters(savedInsight.filters || {}), cleanFilters(filters || {})),
        ],
        isViewedOnDashboard: [
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
                return filters.hidden_legend_keys ?? {}
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
        supportsCsvExport: [
            (s) => [s.insight],
            ({ filters }): boolean => {
                return filters?.insight === InsightType.TRENDS
            },
        ],
        csvExportUrl: [
            (s) => [s.insight, s.currentTeamId, s.supportsCsvExport],
            (insight: Partial<InsightModel>, currentTeamId: number, supportsCsvExport: boolean) => {
                const { filters, name, short_id, derived_name } = insight
                if (filters && supportsCsvExport) {
                    return `/api/projects/${currentTeamId}/insights/trend.csv/?${toParams({
                        ...filterTrendsClientSideParams(filters),
                        export_name: name || derived_name,
                        export_insight_id: short_id,
                    })}`
                }
            },
        ],
    },
    listeners: ({ actions, selectors, values }) => ({
        setFilters: async ({ filters }, _, __, previousState) => {
            const previousFilters = selectors.filters(previousState)
            if (objectsEqual(previousFilters, filters)) {
                return
            }

            // do not make an api call until an actual filter is applied
            const dupeFilters = { ...filters }
            const dupePrevFilters = { ...previousFilters }
            delete dupeFilters.new_entity
            delete dupePrevFilters.new_entity
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
                actions.loadResults()
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
                api.create(`api/projects/${teamLogic.values.currentTeamId}/insights/${values.insight.id}/viewed`)
            }
        },
        reportInsightViewed: async ({ filters, previousFilters }, breakpoint) => {
            await breakpoint(IS_TEST_MODE ? 1 : 500) // Debounce to avoid noisy events from changing filters multiple times
            if (!values.isViewedOnDashboard) {
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
                    changedKeysObj
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
                    changedKeysObj
                )
            }
        },
        startQuery: () => {
            actions.setShowTimeoutMessage(false)
            actions.setShowErrorMessage(false)
            values.timeout && clearTimeout(values.timeout || undefined)
            const view = values.activeView
            actions.setTimeout(
                window.setTimeout(() => {
                    if (values && view == values.activeView) {
                        actions.setShowTimeoutMessage(true)
                        const tags = {
                            insight: values.activeView,
                            scene: sceneLogic.isMounted() ? sceneLogic.values.scene : null,
                        }
                        posthog.capture('insight timeout message shown', tags)
                        captureInternalMetric({ method: 'incr', metric: 'insight_timeout', value: 1, tags })
                    }
                }, SHOW_TIMEOUT_MESSAGE_AFTER)
            )
            actions.setIsLoading(true)
        },
        abortQuery: ({ queryId, view, scene, exception }) => {
            const duration = new Date().getTime() - values.queryStartTimes[queryId]
            const tags = {
                insight: view,
                scene: scene,
                success: !exception,
                ...exception,
            }

            posthog.capture('insight aborted', { ...tags, duration })
            captureInternalMetric({ method: 'timing', metric: 'insight_abort_time', value: duration, tags })
        },
        endQuery: ({ queryId, view, lastRefresh, exception }) => {
            if (values.timeout) {
                clearTimeout(values.timeout)
            }
            if (view === values.activeView) {
                actions.setShowTimeoutMessage(values.maybeShowTimeoutMessage)
                actions.setShowErrorMessage(values.maybeShowErrorMessage)
                actions.setLastRefresh(lastRefresh || null)
                actions.setIsLoading(false)

                const duration = new Date().getTime() - values.queryStartTimes[queryId]
                const tags = {
                    insight: values.activeView,
                    scene: sceneLogic.isMounted() ? sceneLogic.values.scene : null,
                    success: !exception,
                    ...exception,
                }

                posthog.capture('insight loaded', { ...tags, duration })
                captureInternalMetric({ method: 'timing', metric: 'insight_load_time', value: duration, tags })
                if (values.maybeShowErrorMessage) {
                    posthog.capture('insight error message shown', { ...tags, duration })
                }
            }
        },
        setActiveView: ({ type }) => {
            actions.setFilters(cleanFilters({ ...values.filters, insight: type as InsightType }, values.filters))
            actions.setShowTimeoutMessage(false)
            actions.setShowErrorMessage(false)
            if (values.timeout) {
                clearTimeout(values.timeout)
            }
        },
        saveInsight: async ({ redirectToViewMode }) => {
            const insightNumericId =
                values.insight.id || (values.insight.short_id ? await getInsightId(values.insight.short_id) : undefined)
            const { name, description, favorited, filters, deleted, color, dashboards, tags } = values.insight
            let savedInsight: InsightModel

            try {
                if (insightNumericId && emptyFilters(values.insight.filters)) {
                    const error = new Error('Will not override empty filters in saveInsight.')
                    Sentry.captureException(error, {
                        extra: {
                            filters: JSON.stringify(values.insight.filters),
                            insight: JSON.stringify(values.insight),
                        },
                    })
                    throw error
                }

                // We don't want to send ALL of the insight back to the API, so only grabbing fields that might have changed
                const insightRequest: Partial<InsightModel> = {
                    name,
                    derived_name: values.derivedName,
                    description,
                    favorited,
                    filters,
                    deleted,
                    saved: true,
                    color,
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
            lemonToast.success(`Insight saved${dashboards?.length === 1 ? ' & added to dashboard' : ''}`, {
                button: {
                    label: 'View Insights list',
                    action: () => router.actions.push(urls.savedInsights()),
                },
            })
            savedInsightsLogic.findMounted()?.actions.loadInsights()
            dashboardsModel.actions.updateDashboardItem(savedInsight)

            if (redirectToViewMode) {
                const mountedInsightSceneLogic = insightSceneLogic.findMounted()
                if (!insightNumericId && dashboards?.length === 1) {
                    // redirect new insights added to dashboard to the dashboard
                    router.actions.push(urls.dashboard(dashboards[0], savedInsight.short_id))
                } else if (insightNumericId) {
                    mountedInsightSceneLogic?.actions.setInsightMode(ItemMode.View, InsightEventSource.InsightHeader)
                } else {
                    router.actions.push(urls.insightView(savedInsight.short_id))
                }
            }
        },
        saveAs: async () => {
            prompt({ key: `save-as-insight` }).actions.prompt({
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
            if (!insight.result && values.filters) {
                actions.loadResults()
            }
        },
        toggleInsightLegend: () => {
            actions.setFilters({ ...values.filters, show_legend: !values.filters.show_legend })
        },
        toggleVisibility: ({ index }) => {
            const currentIsHidden = !!values.hiddenLegendKeys?.[index]

            actions.setFilters({
                ...values.filters,
                hidden_legend_keys: {
                    ...values.hiddenLegendKeys,
                    [`${index}`]: currentIsHidden ? undefined : true,
                },
            })
        },
        setHiddenById: ({ entry }) => {
            const nextEntries = Object.fromEntries(
                Object.entries(entry).map(([index, hiddenState]) => [index, hiddenState ? true : undefined])
            )

            actions.setFilters({
                ...values.filters,
                hidden_legend_keys: {
                    ...values.hiddenLegendKeys,
                    ...nextEntries,
                },
            })
        },
        cancelChanges: ({ goToViewMode }) => {
            actions.setFilters(values.savedInsight.filters || {})
            if (goToViewMode) {
                insightSceneLogic.findMounted()?.actions.setInsightMode(ItemMode.View, InsightEventSource.InsightHeader)
                eventUsageLogic.actions.reportInsightsTabReset()
            }
        },
    }),

    events: ({ actions, cache, props, values }) => ({
        afterMount: () => {
            if (!props.cachedInsight || !props.cachedInsight?.result || !!props.cachedInsight?.filters) {
                if (
                    props.dashboardItemId &&
                    props.dashboardItemId !== 'new' &&
                    !props.dashboardItemId.startsWith('new-')
                ) {
                    const insight = findInsightFromMountedLogic(props.dashboardItemId, props.dashboardId)
                    if (insight) {
                        actions.setInsight(insight, { overrideFilter: true, fromPersistentApi: true })
                        if (insight?.result) {
                            actions.reportInsightViewed(insight, insight.filters || {})
                        } else {
                            actions.loadResults()
                        }
                        return
                    }
                }
                if (!props.doNotLoad) {
                    if (props.cachedInsight?.filters) {
                        actions.loadResults()
                    } else if (
                        props.dashboardItemId &&
                        props.dashboardItemId !== 'new' &&
                        !props.dashboardItemId.startsWith('new-')
                    ) {
                        actions.loadInsight(props.dashboardItemId as InsightShortId)
                    }
                }
            }
        },
        beforeUnmount: () => {
            cache.abortController?.abort()
            if (values.timeout) {
                clearTimeout(values.timeout)
            }
            lemonToast.dismiss()
        },
    }),
})
