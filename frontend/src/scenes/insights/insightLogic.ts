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

export enum ViewType {
    TRENDS = 'TRENDS',
    STICKINESS = 'STICKINESS',
    LIFECYCLE = 'LIFECYCLE',
    SESSIONS = 'SESSIONS',
    FUNNELS = 'FUNNELS',
    RETENTION = 'RETENTION',
    PATHS = 'PATHS',
}

export const TRENDS_BASED_INSIGHTS = ['TRENDS', 'STICKINESS', 'LIFECYCLE'] // Insights that are based on the same `Trends` components

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

export const insightLogic = kea<insightLogicType>({
    actions: () => ({
        setActiveView: (type: ViewType) => ({ type }),
        updateActiveView: (type) => ({ type }),
        setCachedUrl: (type, url) => ({ type, url }),
        setAllFilters: (filters) => ({ filters }),
        startQuery: true,
        endQuery: (view: string, lastRefresh: string | null, exception?: Record<string, any>) => ({
            view,
            lastRefresh,
            exception,
        }),
        setMaybeShowTimeoutMessage: (showTimeoutMessage: boolean) => ({ showTimeoutMessage }),
        setShowTimeoutMessage: (showTimeoutMessage: boolean) => ({ showTimeoutMessage }),
        setShowErrorMessage: (showErrorMessage: boolean) => ({ showErrorMessage }),
        setIsLoading: (isLoading: boolean) => ({ isLoading }),
        setTimeout: (timeout) => ({ timeout }),
        setLastRefresh: (lastRefresh: string | null) => ({ lastRefresh }),
        setNotFirstLoad: () => {},
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
            ViewType.TRENDS,
            {
                updateActiveView: (_, { type }) => type,
            },
        ],
        timeout: [null, { setTimeout: (_, { timeout }) => timeout }],
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
                    }
                }, SHOW_TIMEOUT_MESSAGE_AFTER)
            )
            actions.setIsLoading(true)
        },
        endQuery: ({ view, lastRefresh, exception }) => {
            clearTimeout(values.timeout || undefined)
            if (view === values.activeView) {
                actions.setShowTimeoutMessage(values.maybeShowTimeoutMessage)
                actions.setShowErrorMessage(values.maybeShowErrorMessage)
                actions.setLastRefresh(lastRefresh || null)
                actions.setIsLoading(false)
                if (values.maybeShowTimeoutMessage) {
                    posthog.capture('insight timeout message shown', { insight: values.activeView, ...exception })
                }
                if (values.maybeShowErrorMessage) {
                    posthog.capture('insight error message shown', { insight: values.activeView, ...exception })
                }
            }
        },
        setActiveView: () => {
            actions.setShowTimeoutMessage(false)
            actions.setShowErrorMessage(false)
            clearTimeout(values.timeout || undefined)
        },
    }),
    actionToUrl: ({ actions, values }) => ({
        setActiveView: ({ type }: { type: string }) => {
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
            clearTimeout(values.timeout || undefined)
        },
    }),
})
