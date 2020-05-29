import { kea } from 'kea'
import { toParams, objectsEqual } from 'lib/utils'
import api from 'lib/api'
import { router } from 'kea-router'
import lo from 'lodash'

export const pathsLogic = kea({
    loaders: ({ values }) => ({
        paths: {
            __default: {
                nodes: [],
                links: [],
            },
            loadPaths: async (_, breakpoint) => {
                const params = toParams({ ...values.filter, properties: values.properties })
                const paths = await api.get(`api/paths${params ? `/?${params}` : ''}`)
                const response = {
                    nodes: [
                        ...paths.map(path => ({ name: path.source, id: path.source_id })),
                        ...paths.map(path => ({ name: path.target, id: path.target_id })),
                    ],
                    links: paths,
                }
                breakpoint()
                return response
            },
        },
    }),
    reducers: () => ({
        initialPathname: [state => router.selectors.location(state).pathname, { noop: a => a }],
        filter: [
            {},
            {
                setFilter: (state, filter) => ({ ...state, ...filter }),
            },
        ],
        properties: [
            {},
            {
                setProperties: (_, { properties }) => properties,
            },
        ],
    }),
    actions: () => ({
        setProperties: properties => ({ properties }),
        setFilter: filter => filter,
    }),
    listeners: ({ actions }) => ({
        setProperties: () => {
            actions.loadPaths()
        },
        setFilter: () => {
            actions.loadPaths()
        },
    }),
    selectors: ({ selectors }) => ({
        propertiesForUrl: [
            () => [selectors.properties, selectors.filter],
            (properties, filter) => {
                let result = {}
                if (!lo.isEmpty(properties)) {
                    result['properties'] = properties
                }

                if (!lo.isEmpty(filter)) {
                    result['filter'] = filter
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
        '*': (_, searchParams) => {
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

            if (
                !objectsEqual(
                    (!lo.isEmpty(searchParams.properties) && searchParams.properties) || {},
                    values.properties
                )
            ) {
                actions.setProperties(searchParams.properties || {})
            }

            if (!objectsEqual(!lo.isEmpty(searchParams.filter) || {}, values.filter)) {
                actions.setFilter(searchParams.filter || {})
            }
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadPaths,
    }),
})
