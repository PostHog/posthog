import { kea } from 'kea'
import { toParams, fromParams, errorToast, clearDOMTextSelection, editingToast } from 'lib/utils'
import posthog from 'posthog-js'
import { DashboardEventSource, eventUsageLogic, InsightEventSource } from 'lib/utils/eventUsageLogic'
import { insightLogicType } from './insightLogicType'
import { DashboardItemType, Entity, FilterType, FunnelVizType, ItemMode, PropertyFilter, ViewType } from '~/types'
import { captureInternalMetric } from 'lib/internalMetrics'
import { Scene, sceneLogic } from 'scenes/sceneLogic'
import { router } from 'kea-router'
import api from 'lib/api'
import { toast } from 'react-toastify'

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
    actions: () => ({
        setActiveView: (type: ViewType) => ({ type }),
        updateActiveView: (type: ViewType) => ({ type }),
        setCachedUrl: (type: ViewType, url: string) => ({ type, url }),
        setAllFilters: (filters) => ({ filters }),
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
    }),

    reducers: {
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
        cachedUrls: [
            {} as Record<string, string>,
            {
                setCachedUrl: (state, { type, url }) => ({ ...state, [type]: url }),
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
        /*
        allfilters is passed to components that are shared between the different insight features
        */
        allFilters: [
            {} as FilterType,
            {
                setAllFilters: (_, { filters }) => filters,
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
    },
    loaders: ({ values, actions }) => ({
        insight: {
            __default: { tags: [] } as Partial<DashboardItemType>,
            loadInsight: async (id: number) => await api.get(`api/insight/${id}`),
            updateInsight: async (payload: Partial<DashboardItemType>, breakpoint) => {
                if (!Object.entries(payload).length) {
                    return
                }
                await breakpoint(700)
                return await api.update(`api/insight/${values.insight.id}`, payload)
            },
            setInsight: (insight) => insight,
        },
        insightMode: [
            ItemMode.View as ItemMode,
            {
                setInsightMode: ({ mode }) => {
                    if (mode === ItemMode.Edit) {
                        clearDOMTextSelection()
                        setTimeout(
                            () =>
                                editingToast(
                                    'Insight',
                                    (insightMode: ItemMode | null, source: DashboardEventSource | null) => {
                                        actions.setInsightMode({ mode: insightMode, source })
                                    }
                                ),
                            100
                        )
                    } else {
                        toast.dismiss()
                    }
                    return mode
                },
            },
        ],
    }),
    selectors: {
        insightName: [(s) => [s.insight], (insight) => insight?.name],
    },
    listeners: ({ actions, values }) => ({
        setAllFilters: async (filters, breakpoint) => {
            const { fromDashboard } = router.values.hashParams
            eventUsageLogic.actions.reportInsightViewed(filters.filters, values.isFirstLoad, Boolean(fromDashboard))
            actions.setNotFirstLoad()

            await breakpoint(10000)
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
        saveNewTag: ({ tag }) => {
            if (values.insight.tags?.includes(tag)) {
                errorToast(undefined, 'Oops! Your insight already has that tag.')
                return
            }
            actions.updateInsight({ tags: [...(values.insight.tags || []), tag] })
        },
        deleteTag: async ({ tag }, breakpoint) => {
            await breakpoint(100)
            actions.updateInsight({ tags: values.insight.tags?.filter((_tag) => _tag !== tag) })
        },
    }),
    actionToUrl: ({ actions, values }) => ({
        setActiveView: ({ type }) => {
            const params = fromParams()
            const { properties, ...restParams } = params

            actions.setCachedUrl(values.activeView, window.location.pathname + '?' + toParams(restParams))
            const cachedUrl = values.cachedUrls[type]
            actions.updateActiveView(type)

            if (cachedUrl) {
                return cachedUrl + '&' + toParams({ properties })
            }

            const urlParams: UrlParams = {
                insight: type,
                properties: values.allFilters.properties,
                filter_test_accounts: defaultFilterTestAccounts(),
                events: (values.allFilters.events || []) as Entity[],
                actions: (values.allFilters.actions || []) as Entity[],
            }

            if (type === ViewType.FUNNELS) {
                urlParams.funnel_viz_type = FunnelVizType.Steps
                urlParams.display = 'FunnelViz'
            }
            return ['/insights', urlParams]
        },
    }),
    urlToAction: ({ actions, values }) => ({
        '/insights': (_: any, searchParams: Record<string, any>, hashParams: Record<string, any>) => {
            if (searchParams.insight && searchParams.insight !== values.activeView) {
                actions.updateActiveView(searchParams.insight)
            }
            if (hashParams.fromItem) {
                actions.loadInsight(hashParams.fromItem)
            }
        },
    }),
    events: ({ values }) => ({
        beforeUnmount: () => {
            if (values.timeout) {
                clearTimeout(values.timeout)
            }
            toast.dismiss()
        },
    }),
})
