import { kea } from 'kea'
import { toParams, fromParams } from 'lib/utils'
import posthog from 'posthog-js'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { insightLogicType } from './insightLogicType'

export const ViewType = {
    TRENDS: 'TRENDS',
    STICKINESS: 'STICKINESS',
    LIFECYCLE: 'LIFECYCLE',
    SESSIONS: 'SESSIONS',
    FUNNELS: 'FUNNELS',
    RETENTION: 'RETENTION',
    PATHS: 'PATHS',
}

/*
InsightLogic maintains state for changing between insight features
This includes handling the urls and view state
*/

const SHOW_TIMEOUT_MESSAGE_AFTER = 15000

export const insightLogic = kea<insightLogicType>({
    actions: () => ({
        setActiveView: (type) => ({ type }),
        updateActiveView: (type) => ({ type }),
        setCachedUrl: (type, url) => ({ type, url }),
        setAllFilters: (filters) => ({ filters }),
        startQuery: true,
        endQuery: (view: string, exception?: Record<string, any>) => ({ view, exception }),
        setMaybeShowTimeoutMessage: (showTimeoutMessage: boolean) => ({ showTimeoutMessage }),
        setShowTimeoutMessage: (showTimeoutMessage: boolean) => ({ showTimeoutMessage }),
        setShowErrorMessage: (showErrorMessage: boolean) => ({ showErrorMessage }),
        setIsLoading: (isLoading: boolean) => ({ isLoading }),
        setTimeout: (timeout) => ({ timeout }),
        setNotFirstLoad: () => {},
    }),

    reducers: () => ({
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
            {} as Record<string, any>,
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
    }),
    listeners: ({ actions, values }) => ({
        setAllFilters: (filters) => {
            eventUsageLogic.actions.reportInsightViewed(filters.filters, values.isFirstLoad)
            actions.setNotFirstLoad()
        },
        startQuery: () => {
            actions.setShowTimeoutMessage(false)
            actions.setShowErrorMessage(false)
            values.timeout && clearTimeout(values.timeout || undefined)
            const view = values.activeView
            actions.setTimeout(
                setTimeout(() => {
                    view == values.activeView && actions.setShowTimeoutMessage(true)
                }, SHOW_TIMEOUT_MESSAGE_AFTER)
            )
            actions.setIsLoading(true)
        },
        endQuery: ({ view, exception }) => {
            clearTimeout(values.timeout || undefined)
            if (view === values.activeView) {
                actions.setShowTimeoutMessage(values.maybeShowTimeoutMessage)
                actions.setShowErrorMessage(values.maybeShowErrorMessage)
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
})
