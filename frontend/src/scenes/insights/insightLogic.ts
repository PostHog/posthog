import { BuiltLogic, kea, Logic } from 'kea'
import { toParams, fromParams } from 'lib/utils'
import posthog from 'posthog-js'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { insightLogicType } from './insightLogicType'
import { retentionTableLogic } from 'scenes/retention/retentionTableLogic'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { trendsLogic } from '../trends/trendsLogic'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { FilterType } from '~/types'
import { sceneLogic } from 'scenes/sceneLogic'
import { captureInternalMetric } from 'lib/internalMetrics'

export enum ViewType {
    TRENDS = 'TRENDS',
    STICKINESS = 'STICKINESS',
    LIFECYCLE = 'LIFECYCLE',
    SESSIONS = 'SESSIONS',
    FUNNELS = 'FUNNELS',
    RETENTION = 'RETENTION',
    PATHS = 'PATHS',
    HISTORY = 'HISTORY',
}

type Timeout = NodeJS.Timeout

export const TRENDS_BASED_INSIGHTS = ['TRENDS', 'SESSIONS', 'STICKINESS', 'LIFECYCLE'] // Insights that are based on the same `Trends` components

/*
InsightLogic maintains state for changing between insight features
This includes handling the urls and view state
*/

const SHOW_TIMEOUT_MESSAGE_AFTER = 15000
export const defaultFilterTestAccounts = (): boolean => {
    return localStorage.getItem('default_filter_test_accounts') === 'true' || false
}

export const logicFromInsight = (insight: string, logicProps: Record<string, any>): Logic & BuiltLogic => {
    if (insight === ViewType.FUNNELS) {
        return funnelLogic(logicProps)
    } else if (insight === ViewType.RETENTION) {
        return retentionTableLogic(logicProps)
    } else if (insight === ViewType.PATHS) {
        return pathsLogic(logicProps)
    } else {
        return trendsLogic(logicProps)
    }
}

export const insightLogic = kea<insightLogicType<ViewType, FilterType, Timeout>>({
    actions: () => ({
        setActiveView: (type: ViewType) => ({ type }),
        updateActiveView: (type: ViewType) => ({ type }),
        setCachedUrl: (type: ViewType, url: string) => ({ type, url }),
        setAllFilters: (filters) => ({ filters }),
        startQuery: (queryId: string) => ({ queryId }),
        endQuery: (queryId: string, view: string, lastRefresh: string | null, exception?: Record<string, any>) => ({
            queryId,
            view,
            lastRefresh,
            exception,
        }),
        setMaybeShowTimeoutMessage: (showTimeoutMessage: boolean) => ({ showTimeoutMessage }),
        setShowTimeoutMessage: (showTimeoutMessage: boolean) => ({ showTimeoutMessage }),
        setShowErrorMessage: (showErrorMessage: boolean) => ({ showErrorMessage }),
        setIsLoading: (isLoading: boolean) => ({ isLoading }),
        setTimeout: (timeout: Timeout | null) => ({ timeout }),
        setLastRefresh: (lastRefresh: string | null) => ({ lastRefresh }),
        setNotFirstLoad: () => {},
        toggleControlsCollapsed: true,
    }),

    reducers: {
        showTimeoutMessage: [false, { setShowTimeoutMessage: (_, { showTimeoutMessage }) => showTimeoutMessage }],
        maybeShowTimeoutMessage: [
            false,
            {
                // Only show timeout message if timer is still running
                setShowTimeoutMessage: (_, { showTimeoutMessage }: { showTimeoutMessage: boolean }) =>
                    showTimeoutMessage,
                endQuery: (_, { exception }) => {
                    if (exception && exception.status !== 500) {
                        return true
                    }
                    return false
                },
                startQuery: () => false,
                setActiveView: () => false,
            },
        ],
        showErrorMessage: [false, { setShowErrorMessage: (_, { showErrorMessage }) => showErrorMessage }],
        maybeShowErrorMessage: [
            false,
            {
                endQuery: (_, { exception }) => exception?.status === 500 || false,
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
        timeout: [null as Timeout | null, { setTimeout: (_, { timeout }) => timeout }],
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
    },
    listeners: ({ actions, values }) => ({
        setAllFilters: (filters) => {
            eventUsageLogic.actions.reportInsightViewed(filters.filters, values.isFirstLoad)
            actions.setNotFirstLoad()
        },
        startQuery: () => {
            actions.setShowTimeoutMessage(false)
            actions.setShowErrorMessage(false)
            actions.setLastRefresh(null)
            values.timeout && clearTimeout(values.timeout || undefined)
            const view = values.activeView
            actions.setTimeout(
                setTimeout(() => {
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
    }),
    actionToUrl: ({ actions, values }) => ({
        setActiveView: ({ type }: { type: ViewType }) => {
            const params = fromParams()
            const { properties, ...restParams } = params

            actions.setCachedUrl(values.activeView, window.location.pathname + '?' + toParams(restParams))
            const cachedUrl = values.cachedUrls[type]
            actions.updateActiveView(type)

            if (cachedUrl) {
                return cachedUrl + '&' + toParams({ properties })
            }

            const urlParams = {
                insight: type,
                properties: values.allFilters.properties,
                filter_test_accounts: defaultFilterTestAccounts(),
            }
            return ['/insights', urlParams]
        },
    }),
    urlToAction: ({ actions, values }) => ({
        '/insights': (_: any, searchParams: Record<string, any>) => {
            if (searchParams.insight && searchParams.insight !== values.activeView) {
                actions.updateActiveView(searchParams.insight)
            }
        },
    }),
    events: ({ values }) => ({
        beforeUnmount: () => {
            if (values.timeout) {
                clearTimeout(values.timeout)
            }
        },
    }),
})
