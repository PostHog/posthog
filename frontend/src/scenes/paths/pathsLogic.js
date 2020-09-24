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

function cleanPathParams(filters, properties) {
    return {
        start_point: filters.start_point,
        path_type: filters.path_type,
        date_from: filters.date_from,
        date_to: filters.date_to,
        properties: properties,
        insight: ViewType.PATHS,
    }
}

export const pathsLogic = kea({
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
    reducers: () => ({
        initialPathname: [(state) => router.selectors.location(state).pathname, { noop: (a) => a }],
        filter: [
            {
                path_type: '$pageview',
            },
            {
                setFilter: (state, filter) => ({ ...state, ...filter }),
            },
        ],
        properties: [
            [],
            {
                setProperties: (_, { properties }) => properties,
            },
        ],
    }),
    actions: () => ({
        setProperties: (properties) => ({ properties }),
        setFilter: (filter) => filter,
    }),
    listeners: ({ actions, values }) => ({
        setProperties: () => {
            actions.loadPaths()
            actions.setAllFilters(cleanPathParams(values.filter, values.properties))
            actions.createInsight(cleanPathParams(values.filter, values.properties))
        },
        setFilter: () => {
            actions.loadPaths()
            actions.setAllFilters(cleanPathParams(values.filter, values.properties))
            actions.createInsight(cleanPathParams(values.filter, values.properties))
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
            return [router.values.location.pathname, values.propertiesForUrl]
        },
        setFilter: () => {
            return [router.values.location.pathname, values.propertiesForUrl]
        },
    }),
    urlToAction: ({ actions, values }) => ({
        '/insights': (_, searchParams) => {
            if (searchParams.insight === ViewType.PATHS) {
                try {
                    // if the url changed, but we are not anymore on the page we were at when the logic was mounted
                    if (router.values.location.pathname !== values.initialPathname) {
                        return
                    }
                } catch (error) {
                    // since this is a catch-all route, this code might run during or after the logic was unmounted
                    // if we have an error accessing the filter value, the logic is gone and we should return
                    return
                }

                if (!objectsEqual(searchParams.properties || [], values.properties)) {
                    actions.setProperties(searchParams.properties || [])
                }

                const { insight: _, properties: __, ...restParams } = searchParams // eslint-disable-line

                if (!objectsEqual(restParams, values.filter)) {
                    actions.setFilter(restParams)
                }
            }
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadPaths,
    }),
})
