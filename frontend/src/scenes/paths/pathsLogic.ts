import { kea } from 'kea'
import { toParams, objectsEqual } from 'lib/utils'
import api from 'lib/api'
import { router } from 'kea-router'
import { ViewType, insightLogic } from 'scenes/insights/insightLogic'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'
import { pathsLogicType } from './pathsLogicType'
import { FilterType, PropertyFilter } from '~/types'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'

export const PAGEVIEW = '$pageview'
export const SCREEN = '$screen'
export const AUTOCAPTURE = '$autocapture'
export const CUSTOM_EVENT = 'custom_event'

export const pathOptionsToLabels = {
    [`${PAGEVIEW}`]: 'Pageview (Web)',
    [`${SCREEN}`]: 'Screen (Mobile)',
    [`${AUTOCAPTURE}`]: 'Autocaptured Events',
    [`${CUSTOM_EVENT}`]: 'Custom Events',
}

export const pathOptionsToProperty = {
    [`${PAGEVIEW}`]: '$current_url',
    [`${SCREEN}`]: '$screen_name',
    [`${AUTOCAPTURE}`]: 'autocaptured_event',
    [`${CUSTOM_EVENT}`]: 'custom_event',
}

function cleanPathParams(filters: Partial<FilterType>): Partial<FilterType> {
    return {
        start_point: filters.start_point,
        path_type: filters.path_type || '$pageview',
        date_from: filters.date_from,
        date_to: filters.date_to,
        insight: ViewType.PATHS,
    }
}

const DEFAULT_PATH_LOGIC_KEY = 'default_path_key'

interface PathResult {
    paths: PathNode[]
    filter: Partial<FilterType>
    error?: boolean
}

interface PathNode {
    target: string
    target_id: number
    source: string
    source_id: number
    value: number
}

export const pathsLogic = kea<pathsLogicType<PathResult, PropertyFilter, FilterType, PathNode>>({
    key: (props) => {
        return props.dashboardItemId || DEFAULT_PATH_LOGIC_KEY
    },
    connect: {
        actions: [insightHistoryLogic, ['createInsight']],
    },
    loaders: ({ values, props }) => ({
        results: {
            __default: { paths: [], filter: {} } as PathResult,
            loadResults: async (refresh = false, breakpoint) => {
                const filter = { ...values.filter, properties: values.properties }
                if (!refresh && (props.cachedResults || props.preventLoading) && values.filter === props.filters) {
                    return { paths: props.cachedResults, filter }
                }
                const params = toParams({ ...filter, ...(refresh ? { refresh: true } : {}) })
                let paths
                insightLogic.actions.startQuery()
                try {
                    paths = await api.get(`api/insight/path${params ? `/?${params}` : ''}`)
                } catch (e) {
                    insightLogic.actions.endQuery(ViewType.PATHS, false, e)
                    return { paths: [], filter, error: true }
                }
                breakpoint()
                insightLogic.actions.endQuery(ViewType.PATHS, paths.last_refresh)
                return { paths: paths.result, filter }
            },
        },
    }),
    reducers: ({ props }) => ({
        filter: [
            (props.filters
                ? cleanPathParams(props.filters as Partial<FilterType>)
                : (state: Record<string, any>) =>
                      cleanPathParams(router.selectors.searchParams(state)) as Record<string, any>) as Partial<
                FilterType
            >,
            {
                setFilter: (state, filter) => ({ ...state, ...filter }),
            },
        ],
        properties: [
            (props.filters
                ? (props.filters as Partial<FilterType>).properties || []
                : (state: Record<string, any>) =>
                      router.selectors.searchParams(state).properties || []) as PropertyFilter[],
            {
                setProperties: (_, { properties }) => properties,
            },
        ],
    }),
    actions: () => ({
        setProperties: (properties) => ({ properties }),
        setFilter: (filter) => filter,
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
                actions.createInsight({ ...cleanPathParams(values.filter), properties: values.properties })
            }
        },
        [dashboardItemsModel.actionTypes.refreshAllDashboardItems]: (filters: Record<string, any>) => {
            if (props.dashboardItemId) {
                actions.setFilter(filters)
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
                        nodes[path.source] = { name: path.source, id: path.source_id }
                    }
                    if (!nodes[path.target]) {
                        nodes[path.target] = { name: path.target, id: path.target_id }
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
    actionToUrl: ({ values }) => ({
        setProperties: () => {
            return ['/insights', values.propertiesForUrl]
        },
        setFilter: () => {
            return ['/insights', values.propertiesForUrl]
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
