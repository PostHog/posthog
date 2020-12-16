import { kea } from 'kea'
import { toParams, objectsEqual } from 'lib/utils'
import api from 'lib/api'
import { router } from 'kea-router'
import { ViewType, insightLogic } from 'scenes/insights/insightLogic'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'

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

function cleanPathParams(filters) {
    return {
        start_point: filters.start_point,
        path_type: filters.path_type || '$pageview',
        date_from: filters.date_from,
        date_to: filters.date_to,
        insight: ViewType.PATHS,
    }
}

const DEFAULT_PATH_LOGIC_KEY = 'default_path_key'

export const pathsLogic = kea({
    key: (props) => {
        return props.dashboardItemId || DEFAULT_PATH_LOGIC_KEY
    },
    connect: {
        actions: [insightLogic, ['setAllFilters'], insightHistoryLogic, ['createInsight']],
    },
    loaders: ({ values }) => ({
        loadedPaths: [
            { paths: [], filter: {} },
            {
                loadPaths: async (_, breakpoint) => {
                    const filter = { ...values.filter, properties: values.properties }
                    const params = toParams(filter)
                    const paths = await api.get(`api/insight/path${params ? `/?${params}` : ''}`)
                    breakpoint()
                    return { paths, filter }
                },
            },
        ],
    }),
    reducers: ({ props }) => ({
        initialPathname: [(state) => router.selectors.location(state).pathname, { noop: (a) => a }],
        filter: [
            props.filters
                ? cleanPathParams(props.filters)
                : (state) => cleanPathParams(router.selectors.searchParams(state)),
            {
                setFilter: (state, filter) => ({ ...state, ...filter }),
            },
        ],
        properties: [
            props.filters
                ? props.filters.properties || []
                : (state) => router.selectors.searchParams(state).properties || [],
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
            actions.loadPaths()
        },
        setFilter: () => {
            actions.loadPaths()
        },
        loadPaths: () => {
            actions.setAllFilters({ ...cleanPathParams(values.filter), properties: values.properties })
            if (!props.dashboardItemId) {
                actions.createInsight({ ...cleanPathParams(values.filter), properties: values.properties })
            }
        },
    }),
    selectors: {
        paths: [
            (s) => [s.loadedPaths],
            (loadedPaths) => {
                const { paths } = loadedPaths

                const nodes = {}
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
                }
                return response
            },
        ],
        loadedFilter: [(s) => [s.loadedPaths, s.filter], (loadedPaths, filter) => loadedPaths?.filter || filter],
        propertiesForUrl: [
            (s) => [s.properties, s.filter],
            (properties, filter) => {
                let result = {
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
        '/insights': (_, searchParams) => {
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
        afterMount: actions.loadPaths,
    }),
})
