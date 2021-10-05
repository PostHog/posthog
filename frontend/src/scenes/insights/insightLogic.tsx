import { kea } from 'kea'
import { errorToast } from 'lib/utils'
import posthog from 'posthog-js'
import { eventUsageLogic, InsightEventSource } from 'lib/utils/eventUsageLogic'
import { insightLogicType } from './insightLogicType'
import { DashboardItemType, FilterType, InsightType, ItemMode, ViewType } from '~/types'
import { captureInternalMetric } from 'lib/internalMetrics'
import { Scene, sceneLogic } from 'scenes/sceneLogic'
import { router } from 'kea-router'
import api from 'lib/api'
import { toast } from 'react-toastify'
import React from 'react'
import { Link } from 'lib/components/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { getInsightUrl } from 'scenes/insights/url'

const IS_TEST_MODE = process.env.NODE_ENV === 'test'

export const TRENDS_BASED_INSIGHTS = ['TRENDS', 'SESSIONS', 'STICKINESS', 'LIFECYCLE'] // Insights that are based on the same `Trends` components

/*
InsightLogic maintains state for changing between insight features
This includes handling the urls and view state
*/

const SHOW_TIMEOUT_MESSAGE_AFTER = 15000

export const insightLogic = kea<insightLogicType>({
    actions: () => ({
        setActiveView: (type: ViewType) => ({ type }),
        updateActiveView: (type: ViewType) => ({ type }),
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
        setInsight: (insight: Partial<DashboardItemType>, shouldMergeWithExisting: boolean = false) => ({
            insight,
            shouldMergeWithExisting,
        }),
        setInsightMode: (mode: ItemMode, source: InsightEventSource | null) => ({ mode, source }),
        setInsightDescription: (description: string) => ({ description }),
        saveInsight: true,
        updateInsightFilters: (filters: FilterType) => ({ filters }),
        setTagLoading: (tagLoading: boolean) => ({ tagLoading }),
    }),
    loaders: ({ values }) => ({
        insight: {
            __default: { tags: [] } as Partial<DashboardItemType>,
            loadInsight: async (id: number) => await api.get(`api/insight/${id}`),
            updateInsight: async (payload: Partial<DashboardItemType>, breakpoint) => {
                if (!Object.entries(payload).length) {
                    return
                }
                await breakpoint(300)
                return await api.update(`api/insight/${values.insight.id}`, payload)
            },
            setInsight: ({ insight, shouldMergeWithExisting }) =>
                shouldMergeWithExisting
                    ? {
                          ...values.insight,
                          ...insight,
                      }
                    : insight,
            updateInsightFilters: ({ filters }) => ({ ...values.insight, filters }),
        },
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
        insightName: [(s) => [s.insight], (insight) => insight.name],
    },
    listeners: ({ actions, values }) => ({
        updateInsightSuccess: () => {
            actions.setInsightMode(ItemMode.View, null)
        },
        setAllFilters: async (filters, breakpoint) => {
            const { fromDashboard } = router.values.hashParams
            eventUsageLogic.actions.reportInsightViewed(filters.filters, values.isFirstLoad, Boolean(fromDashboard))
            actions.setNotFirstLoad()

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
        setActiveView: ({ type }) => {
            actions.setShowTimeoutMessage(false)
            actions.setShowErrorMessage(false)
            if (values.timeout) {
                clearTimeout(values.timeout)
            }
            actions.updateActiveView(type)
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
            toast(
                <div data-attr="success-toast">
                    Insight saved!&nbsp;
                    <Link to={'/saved_insights'}>Click here to see your list of saved insights</Link>
                </div>
            )
        },
        updateInsightFilters: async ({ filters }) => {
            if (featureFlagLogic.values.featureFlags[FEATURE_FLAGS.SAVED_INSIGHTS]) {
                api.update(`api/insight/${values.insight.id}`, { filters })
            }
        },
    }),
    actionToUrl: ({ values }) => ({
        setActiveView: () => {
            return getInsightUrl(
                { ...values.allFilters, insight: values.activeView as InsightType },
                router.values.hashParams,
                values.insight?.id || router.values.hashParams.fromItem
            )
        },
    }),
    urlToAction: ({ actions, values }) => ({
        '/insights': (_, searchParams: Record<string, any>, hashParams: Record<string, any>) => {
            const queryParams = { ...searchParams, ...hashParams.q }
            actions.setAllFilters(queryParams)
            if (queryParams.insight && queryParams.insight !== values.activeView) {
                actions.updateActiveView(queryParams.insight)
            }
            if (hashParams.fromItem) {
                actions.loadInsight(parseInt(hashParams.fromItem))
            } else {
                actions.setInsightMode(ItemMode.Edit, null)
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
