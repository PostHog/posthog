import { kea } from 'kea'
import { toParams, fromParams } from 'lib/utils'
import posthog from 'posthog-js'
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
        isFirstLoad determines if this is the first graph being shown in the session (used for analytics)
        */
        isFirstLoad: [
            true,
            {
                setNotFirstLoad: () => false,
            },
        ],
    }),
    listeners: ({ values, actions }) => ({
        setAllFilters: (payload) => {
            // Reports `insight viewed` event
            const { insight, display, interval, date_from, date_to } = payload.filters
            const properties: Record<string, any> = {
                is_first_load: values.isFirstLoad,
                insight,
                display,
                interval,
                date_from,
                date_to,
                filters_count: payload.filters.properties.length, // Only counts general filters (i.e. not per-event filters)
                events_count: payload.filters.events ? payload.filters.events.length : undefined, // Number of lines in insights graph; number of steps in funnel
            }

            // Custom properties for each insight
            if (insight === 'TRENDS') {
                properties.breakdown_type = payload.filters.breakdown_type
                properties.shown_as = payload.filters.shown_as
            } else if (insight === 'SESSIONS') {
                properties.session_distribution = payload.filters.session
            } else if (insight === 'FUNNELS') {
                properties.session_distribution = payload.filters.session
            } else if (insight === 'RETENTION') {
                properties.period = payload.filters.period
                properties.date_to = payload.filters.date_to
                properties.retention_type = payload.filters.retentionType
                properties.same_retention_and_cohortizing_event =
                    payload.filters.returningEntity.events[0].id === payload.filters.startEntity.events[0].id
            } else if (insight === 'PATHS') {
                properties.path_type = payload.filters.path_type
            }

            const sanitizedProperties: Record<string, any> = {}
            Object.entries(properties).map(([key, value]) => {
                if (value !== undefined) {
                    sanitizedProperties[key] = value
                }
            })
            posthog.capture('insight viewed', sanitizedProperties)
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
