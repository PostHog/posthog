import { kea } from 'kea'
import { errorToast, objectsEqual, toParams, uuid } from 'lib/utils'
import posthog from 'posthog-js'
import { eventUsageLogic, InsightEventSource } from 'lib/utils/eventUsageLogic'
import { insightLogicType } from './insightLogicType'
import {
    DashboardItemType,
    Entity,
    FilterType,
    FunnelVizType,
    InsightLogicProps,
    ItemMode,
    PropertyFilter,
    ViewType,
} from '~/types'
import { captureInternalMetric } from 'lib/internalMetrics'
import { Scene, sceneLogic } from 'scenes/sceneLogic'
import { router } from 'kea-router'
import api from 'lib/api'
import { toast } from 'react-toastify'
import React from 'react'
import { Link } from 'lib/components/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { filterTrendsClientSideParams, keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { dashboardsModel } from '~/models/dashboardsModel'
import { pollFunnel } from 'scenes/funnels/funnelUtils'

const IS_TEST_MODE = process.env.NODE_ENV === 'test'

export const TRENDS_BASED_INSIGHTS = ['TRENDS', 'SESSIONS', 'STICKINESS', 'LIFECYCLE'] // Insights that are based on the same `Trends` components

/*
InsightLogic maintains state for changing between insight features
This includes handling the urls and view state
*/

const SHOW_TIMEOUT_MESSAGE_AFTER = 15000
export const defaultFilterTestAccounts = (): boolean => {
    return localStorage.getItem('default_filter_test_accounts') === 'true' || false
}

interface UrlParams {
    insight: string
    properties: PropertyFilter[] | undefined
    filter_test_accounts: boolean
    funnel_viz_type?: string
    display?: string
    events?: Entity[]
    actions?: Entity[]
}

export const insightLogic = kea<insightLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('new'),

    connect: {
        logic: [eventUsageLogic, dashboardsModel],
    },

    actions: () => ({
        setActiveView: (type: ViewType) => ({ type }),
        updateActiveView: (type: ViewType) => ({ type }),
        setFilters: (filters: Partial<FilterType>) => ({ filters }),
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
        setMaybeShowTimeoutMessage: (showTimeoutMessage: boolean) => ({ showTimeoutMessage }),
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
        fetchedResults: (filters: Partial<FilterType>) => ({ filters }),
        loadResults: (refresh = false) => ({ refresh, queryId: uuid() }),
    }),
    loaders: ({ actions, cache, values, props }) => ({
        insight: [
            {
                id: undefined,
                tags: [],
                filters: props.filters || {},
                result: props.cachedResults || null,
            } as Partial<DashboardItemType>,
            {
                loadInsight: async (id: number) => await api.get(`api/insight/${id}`),
                updateInsight: async (payload: Partial<DashboardItemType>, breakpoint) => {
                    if (!Object.entries(payload).length) {
                        return
                    }
                    await breakpoint(300)
                    return await api.update(`api/insight/${values.insight.id}`, payload)
                },
                // using values.filters, query for new insight results
                loadResults: async ({ refresh, queryId }, breakpoint) => {
                    // fetch this now, as it might be different when we report below
                    const { scene } = sceneLogic.values

                    // If a query is in progress, debounce before making the second query
                    if (cache.abortController) {
                        await breakpoint(300)
                        cache.abortController.abort()
                    }
                    cache.abortController = new AbortController()

                    const { filters } = values
                    const insight = (filters.insight as ViewType | undefined) || ViewType.TRENDS
                    const params = { ...filters, ...(refresh ? { refresh: true } : {}) }

                    const dashboardItemId = props.dashboardItemId
                    actions.startQuery(queryId)
                    if (dashboardItemId) {
                        dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, true, null)
                    }

                    let response
                    try {
                        if (
                            insight === ViewType.TRENDS ||
                            insight === ViewType.STICKINESS ||
                            insight === ViewType.LIFECYCLE
                        ) {
                            response = await api.get(
                                `api/insight/trend/?${toParams(filterTrendsClientSideParams(params))}`,
                                cache.abortController.signal
                            )
                        } else if (insight === ViewType.SESSIONS || filters?.session) {
                            response = await api.get(
                                `api/insight/session/?${toParams(filterTrendsClientSideParams(params))}`,
                                cache.abortController.signal
                            )
                        } else if (insight === ViewType.RETENTION) {
                            response = await api.get(
                                `api/insight/retention/?${toParams(params)}`,
                                cache.abortController.signal
                            )
                        } else if (insight === ViewType.FUNNELS) {
                            response = await pollFunnel(params)
                        } else if (insight === ViewType.PATHS) {
                            response = await api.create(`api/insight/path`, params)
                        } else {
                            throw new Error(`Can not load insight of type ${insight}`)
                        }
                    } catch (e) {
                        if (e.name === 'AbortError') {
                            actions.abortQuery(queryId, insight, scene, e)
                        }
                        breakpoint()
                        cache.abortController = null
                        actions.endQuery(queryId, insight, null, e)
                        if (dashboardItemId) {
                            dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, false, null)
                        }
                        if (filters.insight === ViewType.FUNNELS) {
                            eventUsageLogic.actions.reportFunnelCalculated(
                                filters.events?.length || 0,
                                filters.actions?.length || 0,
                                filters.interval || '',
                                filters.funnel_viz_type,
                                false,
                                e.message
                            )
                        }
                        return values.insight
                    }
                    breakpoint()
                    cache.abortController = null
                    actions.endQuery(
                        queryId,
                        (values.filters.insight as ViewType) || ViewType.TRENDS,
                        response.last_refresh
                    )
                    if (dashboardItemId) {
                        dashboardsModel.actions.updateDashboardRefreshStatus(
                            dashboardItemId,
                            false,
                            response.last_refresh
                        )
                    }
                    if (filters.insight === ViewType.FUNNELS) {
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
                        filters,
                    } as Partial<DashboardItemType>
                },
            },
        ],
    }),
    reducers: ({ props }) => ({
        insight: {
            setInsight: (state, { insight, shouldMergeWithExisting }) =>
                shouldMergeWithExisting
                    ? {
                          ...state,
                          ...insight,
                      }
                    : insight,
            updateInsightFilters: (state, { filters }) => ({ ...state, filters }),
        },
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
                endQuery: (_, { exception }) => exception?.status >= 400,
                startQuery: () => false,
                setActiveView: () => false,
            },
        ],
        activeView: [
            ViewType.TRENDS as ViewType,
            {
                updateActiveView: (_, { type }) => type,
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
        /* filters contains the in-flight filters, might not (yet?) be the same as insight.filters */
        filters: [
            () => props.filters || ({} as Partial<FilterType>),
            {
                setFilters: (_, { filters }) => filters,
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
    }),
    selectors: {
        insightProps: [() => [(_, props) => props], (props): InsightLogicProps => props],
        insightName: [(s) => [s.insight], (insight) => insight.name],
    },
    listeners: ({ actions, values, props }) => ({
        updateInsightSuccess: () => {
            actions.setInsightMode(ItemMode.View, null)
        },
        setFilters: async (filters, breakpoint) => {
            const { fromDashboard } = router.values.hashParams
            eventUsageLogic.actions.reportInsightViewed(filters.filters, values.isFirstLoad, Boolean(fromDashboard))
            actions.setNotFirstLoad()

            // TODO: not always needed to load results, the following is used for funnels
            // // No calculate button on Clickhouse, but query performance is suboptimal on psql
            // const { clickhouseFeaturesEnabled } = values
            // // If user started from empty state (<2 steps) and added a new step
            // const filterLength = (filters: Partial<FilterType>): number =>
            //     (filters?.events?.length || 0) + (filters?.actions?.length || 0)
            // const justAddedSecondFilter = filterLength(values.filters) === 2 && filterLength(values.loadedFilters) === 1
            // // If layout or visibility is the only thing that changes
            // const onlyLayoutOrVisibilityChanged = equal(
            //     Object.assign({}, values.filters, { layout: undefined, hiddenLegendKeys: undefined }),
            //     Object.assign({}, values.loadedFilters, { layout: undefined, hiddenLegendKeys: undefined })
            // )
            //
            // if (!onlyLayoutOrVisibilityChanged && (clickhouseFeaturesEnabled || justAddedSecondFilter)) {
            //     actions.loadResults()
            // }
            actions.loadResults()

            // tests will wait for all breakpoints to finish
            await breakpoint(IS_TEST_MODE ? 1 : 10000)
            eventUsageLogic.actions.reportInsightViewed(filters.filters, values.isFirstLoad, Boolean(fromDashboard), 10)
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
        setActiveView: () => {
            actions.setShowTimeoutMessage(false)
            actions.setShowErrorMessage(false)
            if (values.timeout) {
                clearTimeout(values.timeout)
            }
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
            actions.setInsight({ ...values.insight, tags: [...(values.insight.tags || []), tag] })
            await breakpoint(100)
            actions.setTagLoading(false)
        },
        deleteTag: async ({ tag }, breakpoint) => {
            await breakpoint(100)
            actions.setInsight({ ...values.insight, tags: values.insight.tags?.filter((_tag) => _tag !== tag) })
        },
        saveInsight: async () => {
            const savedInsight = await api.update(`api/insight/${values.insight.id}`, {
                ...values.insight,
                saved: true,
            })
            actions.setInsight(savedInsight)
            actions.setInsightMode(ItemMode.View, InsightEventSource.InsightHeader)
            toast(
                <div data-attr="success-toast">
                    Insight saved!&nbsp;
                    <Link to={'/saved_insights'}>Click here to see your list of saved insights</Link>
                </div>
            )
        },
        updateInsightFilters: async ({ filters }) => {
            // This auto-saves new filters into the insight if results were loaded in any of the sub-logics.
            // Exceptions:
            // - not saved if saved insights are enabled --> it has its own view/edit modes
            // - not saved if on the history "insight"
            // - not saved if came from a dashboard --> there's a separate "save" button for that
            if (props.dashboardItemId && !featureFlagLogic.values.featureFlags[FEATURE_FLAGS.SAVED_INSIGHTS]) {
                if ((filters.insight as ViewType) !== ViewType.HISTORY && !router.values.hashParams.fromDashboard) {
                    await api.update(`api/insight/${props.dashboardItemId}`, { filters })
                }
            }
        },
        loadResultsSuccess: async ({ insight }) => {
            if (!insight.id) {
                const i = await api.create('api/insight', {
                    filters: insight.filters,
                })
                actions.setInsight(i)
                if (props.syncWithUrl) {
                    router.actions.replace('/insights', router.values.searchParams, {
                        ...router.values.hashParams,
                        fromItem: i.id,
                    })
                }
            } else if (insight.filters) {
                actions.updateInsightFilters(insight.filters)
            }
        },
    }),
    actionToUrl: ({ actions, values, props }) => ({
        setFilters: () => {
            if (props.syncWithUrl) {
                return ['/insights', values.filters, router.values.hashParams, { replace: true }]
            }
        },
        setActiveView: ({ type }) => {
            if (props.syncWithUrl) {
                actions.updateActiveView(type)

                const urlParams: UrlParams = {
                    insight: type,
                    properties: values.filters.properties,
                    filter_test_accounts: defaultFilterTestAccounts(),
                    events: (values.filters.events || []) as Entity[],
                    actions: (values.filters.actions || []) as Entity[],
                }

                if (type === ViewType.FUNNELS) {
                    urlParams.funnel_viz_type = FunnelVizType.Steps
                    urlParams.display = 'FunnelViz'
                }
                return ['/insights', urlParams, { ...router.values.hashParams, fromItem: values.insight.id || null }]
            }
        },
    }),
    urlToAction: ({ actions, values, props }) => ({
        '/insights': (_: any, searchParams: Record<string, any>, hashParams: Record<string, any>) => {
            if (props.syncWithUrl) {
                const cleanSearchParams = cleanFilters(searchParams)
                if (!objectsEqual(cleanSearchParams, values.filters)) {
                    actions.setFilters(cleanSearchParams)
                }

                if (searchParams.insight && searchParams.insight !== values.activeView) {
                    actions.updateActiveView(searchParams.insight)
                }
                if (hashParams.fromItem) {
                    if (!values.insight?.id || values.insight?.id !== hashParams.fromItem) {
                        actions.loadInsight(hashParams.fromItem)
                    }
                } else {
                    actions.setInsightMode(ItemMode.Edit, null)
                }
            }
        },
    }),
    events: ({ actions, cache, props, values }) => ({
        afterMount: () => {
            if (!props.cachedResults) {
                if (props.dashboardItemId && !props.filters) {
                    actions.loadInsight(props.dashboardItemId)
                } else {
                    actions.loadResults()
                }
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
