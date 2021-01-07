import { kea } from 'kea'
import { toParams, fromParams } from 'lib/utils'
import { insightLogicType } from 'types/scenes/insights/insightLogicType'

export const ViewType = {
    TRENDS: 'TRENDS',
    SESSIONS: 'SESSIONS',
    FUNNELS: 'FUNNELS',
    RETENTION: 'RETENTION',
    PATHS: 'PATHS',
}
/*
InsighLogic maintains state for changing between insight features
This includes handling the urls and view state
*/

export const insightLogic = kea<insightLogicType>({
    actions: () => ({
        setActiveView: (type) => ({ type }),
        updateActiveView: (type) => ({ type }),
        setCachedUrl: (type, url) => ({ type, url }),
        setAllFilters: (filters) => ({ filters }),
        startQuery: true,
        endQuery: (exception) => ({ exception }),
        setShowTimeoutMessage: (showTimeoutMessage: boolean) => ({ showTimeoutMessage }),
        setTimeout: (timeout) => ({ timeout }),
    }),

    reducers: () => ({
        queryTimer: [
            null,
            {
                startQuery: () => new Date(),
                endQuery: () => null,
            },
        ],
        queryException: [
            null,
            {
                startQuery: () => null,
                endQuery: (_, { exception }: { exception: any }) => exception || null,
            },
        ],
        showTimeoutMessage: [
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
            },
        ],
        showErrorMessage: [
            false,
            {
                endQuery: (_, { exception }) => exception?.status === 500 || false,
                startQuery: () => false,
            },
        ],
        cachedUrls: [
            {},
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
        /*
        allfilters is passed to components that are shared between the different insight features
        */
        allFilters: [
            {},
            {
                setAllFilters: (_, { filters }) => filters,
            },
        ],
    }),
    listeners: ({ actions, values }) => ({
        startQuery: () => {
            values.timeout && clearTimeout(values.timeout)
            actions.setTimeout(setTimeout(() => actions.setShowTimeoutMessage(true), 15000))
        },
        endQuery: () => {
            clearTimeout(values.timeout)
        },
    }),
    actionToUrl: ({ actions, values }) => ({
        setActiveView: ({ type }) => {
            const params = fromParams(window.location.search)
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
        '/insights': (_, searchParams) => {
            if (searchParams.insight && searchParams.insight !== values.activeView) {
                actions.updateActiveView(searchParams.insight)
            }
        },
    }),
})
