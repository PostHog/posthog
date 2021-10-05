import { kea } from 'kea'
import { errorToast, objectsEqual, toParams, toParams as toAPIParams, uuid } from 'lib/utils'
import posthog from 'posthog-js'
import { eventUsageLogic, InsightEventSource } from 'lib/utils/eventUsageLogic'
import { insightLogicType } from './insightLogicType'
import { DashboardItemType, FilterType, InsightType, ItemMode, TrendResult, ViewType } from '~/types'
import { captureInternalMetric } from 'lib/internalMetrics'
import { Scene, sceneLogic } from 'scenes/sceneLogic'
import { router } from 'kea-router'
import api from 'lib/api'
import { toast } from 'react-toastify'
import React from 'react'
import { Link } from 'lib/components/Link'
import { getInsightUrl } from 'scenes/insights/url'
import { dashboardsModel } from '~/models/dashboardsModel'
import { cleanFilters, filterTrendsClientSideParams } from 'scenes/cleanFilters'
import { pollFunnel } from 'scenes/funnels/funnelUtils'

const IS_TEST_MODE = process.env.NODE_ENV === 'test'

export const TRENDS_BASED_INSIGHTS = ['TRENDS', 'SESSIONS', 'STICKINESS', 'LIFECYCLE'] // Insights that are based on the same `Trends` components

/*
InsightLogic maintains state for changing between insight features
This includes handling the urls and view state
*/

const SHOW_TIMEOUT_MESSAGE_AFTER = 15000

export interface InsightLogicProps {
    id: number | 'new'
    from?: 'dashboard' | 'scene'
}
export const insightLogic = kea<insightLogicType<InsightLogicProps>>({
    props: {} as InsightLogicProps,
    key: (props) => props.id || 'new',
    actions: () => ({
        setActiveView: (type: InsightType) => ({ type }),
        setFilters: (filters: Partial<FilterType>, mergeFilters = true) => ({ filters, mergeFilters }),
        startQuery: (queryId: string) => ({ queryId }),
        endQuery: (queryId: string, view: ViewType, lastRefresh: string | null, exception?: Record<string, any>) => ({
            queryId,
            view,
            lastRefresh,
            exception,
        }),
        abortQuery: (queryId: string, view: ViewType, scene: Scene | null, exception?: Record<string, any>) => ({
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
        setNotFirstLoad: () => {},
        toggleControlsCollapsed: true,
        saveNewTag: (tag: string) => ({ tag }),
        deleteTag: (tag: string) => ({ tag }),
        setInsight: (insight: Partial<DashboardItemType>, shouldMergeWithExisting: boolean = false) => ({
            insight,
            shouldMergeWithExisting,
        }),
        setInsightMode: (mode: ItemMode, source: InsightEventSource | null) => ({ mode, source }),
        setInsightDescription: (description: string) => ({ description }),
        saveInsight: true,
        updateInsightFilters: (filters: FilterType) => ({ filters }),
        setTagLoading: (tagLoading: boolean) => ({ tagLoading }),
        setCachedResults: (filters: Partial<FilterType>, results: TrendResult[]) => ({ filters, results }),
    }),
    loaders: ({ actions, cache, values, props }) => ({
        insight: [
            { id: props.id, tags: [], filters: {}, result: null } as Partial<DashboardItemType>,
            {
                loadInsight: async (id: number) => await api.get(`api/insight/${id}`),
                setInsight: ({ insight, shouldMergeWithExisting }) =>
                    shouldMergeWithExisting
                        ? {
                              ...values.insight,
                              ...insight,
                          }
                        : insight,
                updateInsight: async (payload: Partial<DashboardItemType>, breakpoint) => {
                    if (!Object.entries(payload).length) {
                        return
                    }
                    await breakpoint(300)
                    if (!values.insight.id) {
                        // TODO: premount perhaps?
                        return await api.create(`api/insight`, payload)
                    } else {
                        return await api.update(`api/insight/${values.insight.id}`, payload)
                    }
                },

                setCachedResults: ({ results, filters }) => {
                    return { result: results, filters }
                },
                loadResults: async (refresh = false, breakpoint) => {
                    // fetch this now, as it might be different when we report below
                    const { scene } = sceneLogic.values

                    // If a query is in progress, debounce before making the second query
                    if (cache.abortController) {
                        await breakpoint(300)
                        cache.abortController.abort()
                    }
                    cache.abortController = new AbortController()

                    const queryId = uuid()
                    const dashboardItemId = typeof props.id === 'number' ? props.id : undefined

                    actions.startQuery(queryId)
                    if (dashboardItemId) {
                        dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, true, null)
                    }

                    const { filters } = values

                    let response
                    try {
                        if (filters.insight === ViewType.PATHS) {
                            const params = toParams({ ...filters, ...(refresh ? { refresh: true } : {}) })
                            response = await api.get(`api/insight/path${params ? `/?${params}` : ''}`)
                        } else if (filters.insight === ViewType.FUNNELS) {
                            response = await pollFunnel({
                                ...cleanFilters(filters),
                                refresh,
                                from_dashboard: typeof props.id === 'number' ? props.id : undefined,
                            })
                        } else if (filters.insight === ViewType.SESSIONS || filters?.session) {
                            response = await api.get(
                                'api/insight/session/?' +
                                    (refresh ? 'refresh=true&' : '') +
                                    toAPIParams(filterTrendsClientSideParams(filters)),
                                cache.abortController.signal
                            )
                        } else {
                            response = await api.get(
                                'api/insight/trend/?' +
                                    (refresh ? 'refresh=true&' : '') +
                                    toAPIParams(filterTrendsClientSideParams(filters)),
                                cache.abortController.signal
                            )
                        }
                    } catch (e) {
                        if (e.name === 'AbortError') {
                            actions.abortQuery(queryId, (filters.insight as ViewType) || ViewType.TRENDS, scene, e)
                        }
                        breakpoint()
                        cache.abortController = null
                        actions.endQuery(queryId, (filters.insight as ViewType) || ViewType.TRENDS, null, e)
                        if (dashboardItemId) {
                            dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, false, null)
                        }
                        return []
                    }
                    breakpoint()
                    cache.abortController = null
                    actions.endQuery(queryId, (filters.insight as ViewType) || ViewType.TRENDS, response.last_refresh)
                    if (dashboardItemId) {
                        dashboardsModel.actions.updateDashboardRefreshStatus(
                            dashboardItemId,
                            false,
                            response.last_refresh
                        )
                    }

                    return { ...response, filters }
                },
            },
        ],
    }),
    reducers: {
        filters: [
            // (state: Record<string, any>) =>
            //     cleanFilters(selectors.insight(state)?.filters || {})
            {} as Partial<FilterType>,
            {
                setFilters: (state, { filters, mergeFilters }) => {
                    return cleanFilters({
                        ...(mergeFilters ? state : {}),
                        ...filters,
                    })
                },
                setCachedResults: (_, { filters }) => filters,
            },
        ],
        showTimeoutMessage: [
            false,
            { setShowTimeoutMessage: (_, { showTimeoutMessage }) => showTimeoutMessage, startQuery: () => false },
        ],
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
        showErrorMessage: [
            false,
            { setShowErrorMessage: (_, { showErrorMessage }) => showErrorMessage, startQuery: () => false },
        ],
        maybeShowErrorMessage: [
            false,
            {
                endQuery: (_, { exception }) => exception?.status >= 400,
                startQuery: () => false,
                setActiveView: () => false,
            },
        ],
        timeout: [null as number | null, { setTimeout: (_, { timeout }) => timeout }],
        lastRefresh: [
            null as string | null,
            {
                setLastRefresh: (_, { lastRefresh }) => lastRefresh,
                setActiveView: () => null,
            },
        ],
        isLoading: [
            false,
            {
                setIsLoading: (_, { isLoading }) => isLoading,
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
        controlsCollapsed: [
            false,
            {
                toggleControlsCollapsed: (state) => !state,
            },
        ],
        queryStartTimes: [
            {} as Record<string, number>,
            {
                startQuery: (state, { queryId }) => ({ ...state, [queryId]: new Date().getTime() }),
            },
        ],
        lastInsightModeSource: [
            null as InsightEventSource | null,
            {
                setInsightMode: (_, { source }) => source,
            },
        ],
        insightMode: [
            ItemMode.View as ItemMode,
            {
                setInsightMode: (_, { mode }) => mode,
            },
        ],
        tagLoading: [
            false,
            {
                setTagLoading: (_, { tagLoading }) => tagLoading,
            },
        ],
    },
    selectors: {
        insightFilters: [(s) => [s.insight], (insight): Partial<FilterType> => insight.filters || {}],
        insightName: [(s) => [s.insight], (insight) => insight.name],
        results: [(s) => [s.insight], (insight) => insight.result],
        resultsLoading: [(s) => [s.insightLoading], (loading) => loading],
        activeView: [(s) => [s.filters], (filters) => filters.insight],
        areFiltersValid: [(s) => [s.filters], (filters) => objectsEqual(filters, cleanFilters(filters))],
    },
    listeners: ({ actions, values, props }) => ({
        updateInsightSuccess: () => {
            actions.setInsightMode(ItemMode.View, null)
        },
        loadResultsSuccess: () => {
            // actions.updateInsightResults(values.results)
            actions.updateInsightFilters(values.filters)
        },
        setFilters: async ({ filters }, breakpoint) => {
            const { isFirstLoad } = values

            if (!objectsEqual(values.insightFilters, filters)) {
                actions.loadResults()
            }

            if (isFirstLoad) {
                actions.setNotFirstLoad()
            }

            const fromDashboard = props.from === 'dashboard'
            eventUsageLogic.actions.reportInsightViewed(filters, isFirstLoad, fromDashboard)
            // tests will wait for all breakpoints to finish
            await breakpoint(IS_TEST_MODE ? 1 : 10000)
            eventUsageLogic.actions.reportInsightViewed(filters, isFirstLoad, fromDashboard, 10)
        },
        startQuery: () => {
            values.timeout && clearTimeout(values.timeout || undefined)
            const view = values.activeView
            actions.setTimeout(
                window.setTimeout(() => {
                    if (values && view == values.activeView) {
                        actions.setShowTimeoutMessage(true)
                        const tags = {
                            insight: values.activeView,
                            scene: sceneLogic.values.scene,
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
                    scene: sceneLogic.values.scene,
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
            actions.setShowTimeoutMessage(false)
            actions.setShowErrorMessage(false)
            if (values.timeout) {
                clearTimeout(values.timeout)
            }
            actions.setFilters({ insight: type })
        },
        toggleControlsCollapsed: async () => {
            eventUsageLogic.actions.reportInsightsControlsCollapseToggle(values.controlsCollapsed)
        },
        saveNewTag: async ({ tag }, breakpoint) => {
            actions.setTagLoading(true)
            if (values.insight.tags?.includes(tag)) {
                errorToast(undefined, 'Oops! Your insight already has that tag.')
                actions.setTagLoading(false)
                return
            }
            actions.setInsight({ tags: [...(values.insight.tags || []), tag] }, true)
            await breakpoint(100)
            actions.setTagLoading(false)
        },
        deleteTag: async ({ tag }, breakpoint) => {
            await breakpoint(100)
            actions.setInsight({ tags: values.insight.tags?.filter((_tag) => _tag !== tag) }, true)
        },
        saveInsight: async () => {
            const savedInsight = await api.update(`api/insight/${values.insight.id}`, {
                ...values.insight,
                saved: true,
            })
            actions.setInsight(savedInsight)
            toast(
                <div data-attr="success-toast">
                    Insight saved!&nbsp;
                    <Link to={'/saved_insights'}>Click here to see your list of saved insights</Link>
                </div>
            )
        },
        updateInsightFilters: async ({ filters }) => {
            if (!values.insight.id) {
                actions.updateInsight({ filters })
            } else {
                actions.setInsight({ filters }, true)
            }
        },
    }),
    actionToUrl: ({ values, props }) => ({
        setFilters: () => {
            if (props.from === 'scene') {
                return getInsightUrl(
                    values.filters,
                    router.values.hashParams,
                    values.insight?.id || router.values.hashParams.fromItem
                )
            }
        },
    }),
    urlToAction: ({ actions, values, props }) => ({
        '/insights': (_, searchParams: Record<string, any>, hashParams: Record<string, any>) => {
            if (props.from === 'scene') {
                const queryParams = { ...searchParams, ...hashParams.q }
                actions.setFilters(cleanFilters(queryParams), false)
                if (hashParams.fromItem) {
                    if (values.insight?.id !== hashParams.fromItem && Object.keys(queryParams).length === 0) {
                        actions.loadInsight(parseInt(hashParams.fromItem))
                    }
                } else {
                    actions.setInsightMode(ItemMode.Edit, null)
                }
            }
        },
    }),
    events: ({ cache, values, props, actions }) => ({
        afterMount: () => {
            if (!props.id) {
                debugger
            }
            if (props.id && props.id !== 'new') {
                actions.loadInsight(props.id)
            } else {
                actions.loadResults()
            }
        },
        beforeUnmount: () => {
            cache.abortController?.abort()
            if (values.timeout) {
                clearTimeout(values.timeout)
            }
            toast.dismiss()
        },
    }),
})
// actionToUrl: ({ values, props }) => ({
//     setFilters: () => {
//         if (!props.dashboardItemId) {
//             return getInsightUrl(
//                 values.propertiesForUrl,
//                 router.values.hashParams,
//                 router.values.hashParams.fromItem
//             )
//         }
//     },
//     clearFunnel: () => {
//         if (!props.dashboardItemId) {
//             return getInsightUrl(
//                 { insight: ViewType.FUNNELS },
//                 router.values.hashParams,
//                 router.values.hashParams.fromItem
//             )
//         }
//     },
// }),
// events: ({ actions, values }) => ({
//     afterMount: () => {
//         if (values.areFiltersValid) {
//             // loadResults gets called in urlToAction for non-dashboard insights
//             actions.loadResults()
//         }
//     },
// }),
