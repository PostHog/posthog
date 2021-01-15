import { kea } from 'kea'
import { toParams, fromParams } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { insightLogicType } from 'types/scenes/insights/insightLogicType'

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

export const insightLogic = kea<insightLogicType>({
    actions: () => ({
        setActiveView: (type) => ({ type }),
        updateActiveView: (type) => ({ type }),
        setCachedUrl: (type, url) => ({ type, url }),
        setAllFilters: (filters) => ({ filters }),
        setNotFirstLoad: () => {},
    }),
    reducers: () => ({
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
        /*
        allfilters is passed to components that are shared between the different insight features
        */
        allFilters: [
            {},
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
