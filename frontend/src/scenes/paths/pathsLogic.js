import { kea } from 'kea'
import { toParams, objectsEqual } from 'lib/utils'
import api from 'lib/api'
import { router } from 'kea-router'
import lo from 'lodash'
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

function checkRoot(nodeToVerify, paths, start) {
    let tempSource = paths.find((node) => node.target === nodeToVerify.source)
    while (tempSource !== undefined && !(tempSource.source.includes('1_') && tempSource.source.includes(start))) {
        tempSource = paths.find((node) => node.target === tempSource.source)
    }
    return tempSource
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
    loaders: ({ values }) => ({
        paths: {
            __default: {
                nodes: [],
                links: [],
            },
            loadPaths: async (_, breakpoint) => {
                const params = toParams({ ...values.filter, properties: values.properties })
                let paths = await api.get(`api/insight/path${params ? `/?${params}` : ''}`)
                if (values.filter.start_point) {
                    paths = paths.filter((checkingNode) => {
                        return (
                            checkingNode.source.includes(values.filter.start_point) ||
                            checkRoot(checkingNode, paths, values.filter.start_point)
                        )
                    })
                }
                const response = {
                    nodes: [
                        ...paths.map((path) => ({ name: path.source, id: path.source_id })),
                        ...paths.map((path) => ({ name: path.target, id: path.target_id })),
                    ],
                    links: paths,
                }
                breakpoint()
                return response
            },
        },
    }),
    connect: {
        actions: [insightLogic, ['setAllFilters'], insightHistoryLogic, ['createInsight']],
    },
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
            if (
                values.filter.path_type !== AUTOCAPTURE ||
                (values.filter.path_type === AUTOCAPTURE && !isNaN(values.filter.start_point))
            )
                actions.loadPaths()

            actions.setAllFilters(cleanPathParams(values.filter, values.properties))
            actions.createInsight(cleanPathParams(values.filter, values.properties))
        },
    }),
    selectors: ({ selectors }) => ({
        propertiesForUrl: [
            () => [selectors.properties, selectors.filter],
            (properties, filter) => {
                let result = {
                    insight: ViewType.PATHS,
                }
                if (!lo.isEmpty(properties)) {
                    result['properties'] = properties
                }

                if (!lo.isEmpty(filter)) {
                    result = {
                        ...result,
                        ...filter,
                    }
                }

                if (lo.isEmpty(result)) return ''
                return result
            },
        ],
    }),
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
