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
interface FilterType {
    insight: 'TRENDS' | 'SESSIONS' | 'FUNNELS' | 'RETENTION' | 'PATHS'
    display?:
        | 'ActionsLineGraph'
        | 'ActionsLineGraphCumulative'
        | 'ActionsTable'
        | 'ActionsPie'
        | 'ActionsBar'
        | 'PathsViz'
        | 'FunnelViz'
    interval?: string
    date_from?: string
    date_to?: string
    properties?: Record<string, any>[]
    events?: Record<string, any>[]
    actions?: Record<string, any>[]
    breakdown_type?: 'cohort' | 'person' | 'event'
    shown_as?: 'Volume' | 'Stickiness' | 'Lifecycle'
    session?: string
    period?: string
    retentionType?: 'retention_recurring' | 'retention_first_time'
    returningEntity?: Record<string, any>
    startEntity?: Record<string, any>
    path_type?: '$pageview' | '$screen' | '$autocapture' | 'custom_event'
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
        reportUsage: (filters) => filters, // Reports usage via `posthog.capture`
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
    listeners: ({ values, actions }) => ({
        setAllFilters: (filters) => {
            actions.reportUsage(filters.filters)
            actions.setNotFirstLoad()
        },
        reportUsage: async (filters: FilterType, breakpoint) => {
            // Reports `insight viewed` event
            const { insight, display, interval, date_from, date_to } = filters
            const properties: Record<string, any> = {
                is_first_component_load: values.isFirstLoad,
                insight,
                display,
                interval,
                date_from,
                date_to,
                filters_count: filters.properties?.length || 0, // Only counts general filters (i.e. not per-event filters)
                events_count: filters.events?.length, // Number of event lines in insights graph; number of steps in funnel
                actions_count: filters.actions?.length, // Number of action lines in insights graph; number of steps in funnel
            }

            properties.total_event_actions_count = (properties.events_count || 0) + (properties.actions_count || 0)

            await breakpoint(5000)

            // Custom properties for each insight
            if (insight === 'TRENDS') {
                properties.breakdown_type = filters.breakdown_type
                properties.shown_as = filters.shown_as
            } else if (insight === 'SESSIONS') {
                properties.session_distribution = filters.session
            } else if (insight === 'FUNNELS') {
                properties.session_distribution = filters.session
            } else if (insight === 'RETENTION') {
                properties.period = filters.period
                properties.date_to = filters.date_to
                properties.retention_type = filters.retentionType
                properties.same_retention_and_cohortizing_event =
                    filters.returningEntity?.events[0].id === filters.startEntity?.events[0].id
            } else if (insight === 'PATHS') {
                properties.path_type = filters.path_type
            }

            posthog.capture('insight viewed', properties)
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
