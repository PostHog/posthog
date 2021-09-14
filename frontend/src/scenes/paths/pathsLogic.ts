import { kea } from 'kea'
import { toParams, objectsEqual, uuid } from 'lib/utils'
import api from 'lib/api'
import { router } from 'kea-router'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'
import { pathsLogicType } from './pathsLogicType'
import { FilterType, PathType, PropertyFilter, ViewType } from '~/types'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { dashboardsModel } from '~/models/dashboardsModel'

export const pathOptionsToLabels = {
    [PathType.PageView]: 'Page views (Web)',
    [PathType.Screen]: 'Screen views (Mobile)',
    [PathType.AutoCapture]: 'Autocaptured events',
    [PathType.CustomEvent]: 'Custom events',
}

export const pathOptionsToProperty = {
    [PathType.PageView]: '$current_url',
    [PathType.Screen]: '$screen_name',
    [PathType.AutoCapture]: 'autocaptured_event',
    [PathType.CustomEvent]: 'custom_event',
}

function cleanPathParams(filters: Partial<FilterType>): Partial<FilterType> {
    return {
        start_point: filters.start_point,
        path_type: filters.path_type || PathType.PageView,
        date_from: filters.date_from,
        date_to: filters.date_to,
        insight: ViewType.PATHS,
        ...(filters.filter_test_accounts ? { filter_test_accounts: filters.filter_test_accounts } : {}),
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
    source: string
    value: number
}

export const pathsLogic = kea<pathsLogicType<PathNode, PathResult>>({
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
        filtersLoading: [
            () => [featureFlagLogic.selectors.featureFlags, propertyDefinitionsModel.selectors.loaded],
            (featureFlags, loaded) => !featureFlags[FEATURE_FLAGS.TAXONOMIC_PROPERTY_FILTER] && !loaded,
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
