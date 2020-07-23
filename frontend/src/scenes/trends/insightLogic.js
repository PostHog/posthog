import { kea } from 'kea'

export const ViewType = {
    TRENDS: 'TRENDS',
    SESSIONS: 'SESSIONS',
    FUNNELS: 'FUNNELS',
    RETENTION: 'RETENTION',
    PATHS: 'PATHS',
}

export const insightLogic = kea({
    actions: () => ({
        setActiveView: (type) => ({ type }),
        updateActiveView: (type) => ({ type }),
        setCachedUrl: (type, url) => ({ type, url }),
        setAllFilters: (filters) => ({ filters }),
    }),
    reducers: ({ actions }) => ({
        cachedUrls: [
            {},
            {
                [actions.setCachedUrl]: (state, { type, url }) => ({ ...state, [type]: url }),
            },
        ],
        activeView: [
            ViewType.TRENDS,
            {
                updateActiveView: (_, { type }) => type,
            },
        ],
        allFilters: [
            {},
            {
                setAllFilters: (_, { filters }) => filters,
            },
        ],
    }),
    actionToUrl: ({ actions, values }) => ({
        [actions.setActiveView]: ({ type }) => {
            actions.setCachedUrl(values.activeView, window.location.pathname + window.location.search)
            const cachedUrl = values.cachedUrls[type]
            actions.updateActiveView(type)

            if (cachedUrl) {
                return cachedUrl
            }
            const urlParams = {
                insight: type,
            }
            return ['/trends', urlParams]
        },
    }),
    urlToAction: ({ actions, values }) => ({
        '/trends': (_, searchParams) => {
            if (searchParams.insight && searchParams.insight !== values.activeView) {
                actions.updateActiveView(searchParams.insight)
            }
        },
    }),
})
