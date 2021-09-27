import { kea } from 'kea'
import { toParams, objectsEqual, uuid } from 'lib/utils'
import api from 'lib/api'
import { router } from 'kea-router'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'
import { pathsLogicType } from './pathsLogicType'
import { DashboardItemLogicProps, FilterType, PathType, PropertyFilter, ViewType } from '~/types'
import { dashboardsModel } from '~/models/dashboardsModel'

export const pathOptionsToLabels = {
    [PathType.PageView]: 'Page views (Web)',
    [PathType.Screen]: 'Screen views (Mobile)',
    [PathType.CustomEvent]: 'Custom events',
}

export const pathOptionsToProperty = {
    [PathType.PageView]: '$current_url',
    [PathType.Screen]: '$screen_name',
    [PathType.CustomEvent]: 'custom_event',
}

function cleanPathParams(filters: Partial<FilterType>): Partial<FilterType> {
    return {
        start_point: filters.start_point,
        end_point: filters.end_point,
        start_point_type: filters.start_point_type,
        end_point_type: filters.end_point_type,
        path_type: filters.path_type || PathType.PageView,
        include_event_types: filters.include_event_types || [PathType.PageView],
        groupings: filters.groupings || [],
        ...(filters.include_event_types ? { include_event_types: filters.include_event_types } : {}),
        date_from: filters.date_from,
        date_to: filters.date_to,
        insight: ViewType.PATHS,
        ...(filters.filter_test_accounts ? { filter_test_accounts: filters.filter_test_accounts } : {}),
    }
}

const DEFAULT_PATH_LOGIC_KEY = 'default_path_key'

export interface PathItem {
    type?: PathType
    item?: string | undefined | null
}
interface PathResult {
    paths: PathNode[]
    filter: Partial<FilterType>
    error?: boolean
}

interface PathNode {
    target: string
    source: string
    value: number
}

export const pathsLogic = kea<pathsLogicType<PathNode, PathResult>>({
    props: {} as DashboardItemLogicProps,
    key: (props) => {
        return props.dashboardItemId || DEFAULT_PATH_LOGIC_KEY
    },
    connect: {
        actions: [insightHistoryLogic, ['createInsight']],
    },
    actions: {
        setProperties: (properties) => ({ properties }),
        setFilter: (filter) => filter,
        setCachedResults: (filters: Partial<FilterType>, results: any) => ({ filters, results }),
        showPathEvents: (event) => ({ event }),
        addImportantEvent: (event) => ({ event }),
        addExcludedEvent: (event) => ({ event }),
        removeImportantEvent: (event) => ({ event }),
        removeExcludedEvent: (event) => ({ event }),
    },
    loaders: ({ values, props }) => ({
        results: {
            __default: { paths: [], filter: {} } as PathResult,
            setCachedResults: ({ results, filters }) => {
                return {
                    paths: results,
                    filters: filters,
                }
            },
            loadResults: async (refresh = false, breakpoint) => {
                const filter = { ...values.filter, properties: values.properties }
                if (!refresh && (props.cachedResults || props.preventLoading) && values.filter === props.filters) {
                    return { paths: props.cachedResults, filter }
                }
                const params = toParams({ ...filter, ...(refresh ? { refresh: true } : {}) })

                const queryId = uuid()
                const dashboardItemId = props.dashboardItemId as number | undefined
                insightLogic.actions.startQuery(queryId)
                dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, true, null)

                let paths
                try {
                    paths = await api.get(`api/insight/path${params ? `/?${params}` : ''}`)
                } catch (e) {
                    breakpoint()
                    insightLogic.actions.endQuery(queryId, ViewType.PATHS, null, e)
                    dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, false, null)

                    return { paths: [], filter, error: true }
                }
                breakpoint()
                insightLogic.actions.endQuery(queryId, ViewType.PATHS, paths.last_refresh)
                dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, false, paths.last_refresh)

                return { paths: paths.result, filter }
            },
        },
    }),
    reducers: ({ props }) => ({
        filter: [
            (props.filters
                ? cleanPathParams(props.filters)
                : (state: Record<string, any>) => cleanPathParams(router.selectors.searchParams(state))) as Partial<
                FilterType
            >,
            {
                setFilter: (state, filter) => ({ ...state, ...filter }),
                showPathEvents: (state, { event }) => {
                    if (state.include_event_types) {
                        const include_event_types = state.include_event_types.includes(event)
                            ? state.include_event_types.filter((e) => e !== event)
                            : [...state.include_event_types, event]
                        return { ...state, include_event_types }
                    }
                    return { ...state, include_event_types: [event] }
                },
            },
        ],
        properties: [
            (props.filters
                ? props.filters.properties || []
                : (state: Record<string, any>) =>
                      router.selectors.searchParams(state).properties || []) as PropertyFilter[],
            {
                setProperties: (_, { properties }) => properties,
            },
        ],
        importantEvents: [
            [],
            {
                addImportantEvent: (state, { event }) => [...state, event],
                removeImportantEvent: (state, { event }) => state.filter((e) => e !== event),
            },
        ],
        excludedEvents: [
            [],
            {
                addExcludedEvent: (state, { event }) => [...state, event],
                removeExcludedEvent: (state, { event }) => state.filter((e) => e !== event),
            },
        ],
    }),
    listeners: ({ actions, values, props }) => ({
        setProperties: () => {
            actions.loadResults(true)
        },
        setFilter: () => {
            actions.loadResults(true)
        },
        loadResults: () => {
            insightLogic.actions.setAllFilters({ ...cleanPathParams(values.filter), properties: values.properties })
            if (!props.dashboardItemId) {
                if (!insightLogic.values.insight.id) {
                    actions.createInsight({ ...cleanPathParams(values.filter), properties: values.properties })
                } else {
                    insightLogic.actions.updateInsightFilters(values.filter)
                }
            }
        },
    }),
    selectors: {
        paths: [
            (s) => [s.results],
            (results: PathResult) => {
                const { paths, error } = results

                const nodes: Record<string, any> = {}
                for (const path of paths) {
                    if (!nodes[path.source]) {
                        nodes[path.source] = { name: path.source }
                    }
                    if (!nodes[path.target]) {
                        nodes[path.target] = { name: path.target }
                    }
                }

                const response = {
                    nodes: Object.values(nodes),
                    links: paths,
                    error,
                }
                return response
            },
        ],
        loadedFilter: [
            (s) => [s.results, s.filter],
            (results: PathResult, filter: Partial<FilterType>) => results?.filter || filter,
        ],
        propertiesForUrl: [
            (s) => [s.properties, s.filter],
            (properties: PropertyFilter[], filter: Partial<FilterType>) => {
                let result: Partial<FilterType> = {
                    insight: ViewType.PATHS,
                }
                if (properties && properties.length > 0) {
                    result['properties'] = properties
                }

                if (filter && Object.keys(filter).length > 0) {
                    result = {
                        ...result,
                        ...filter,
                    }
                }

                return Object.keys(result).length === 0 ? '' : result
            },
        ],
    },
    actionToUrl: ({ values, props }) => ({
        setProperties: () => {
            if (!props.dashboardItemId) {
                return ['/insights', values.propertiesForUrl, undefined, { replace: true }]
            }
        },
        setFilter: () => {
            if (!props.dashboardItemId) {
                return ['/insights', values.propertiesForUrl, undefined, { replace: true }]
            }
        },
    }),
    urlToAction: ({ actions, values, key }) => ({
        '/insights': ({}, searchParams: Partial<FilterType>) => {
            if (searchParams.insight === ViewType.PATHS) {
                if (key != DEFAULT_PATH_LOGIC_KEY) {
                    return
                }
                const cleanedPathParams = cleanPathParams(searchParams)

                if (!objectsEqual(cleanedPathParams, values.filter)) {
                    actions.setFilter(cleanedPathParams)
                }

                if (!objectsEqual(searchParams.properties || [], values.properties)) {
                    actions.setProperties(searchParams.properties || [])
                }
            }
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => actions.loadResults(),
    }),
})
