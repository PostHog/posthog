import { kea } from 'kea'
import { toParams, objectsEqual } from 'lib/utils'
import api from 'lib/api'
import { router } from 'kea-router'

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
            {
                dateFrom: null,
                dateTo: null,
            },
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
            () => [selectors.properties],
            properties => {
                if (Object.keys(properties).length > 0) {
                    return { properties }
                } else {
                    return ''
                }
            },
        ],
    }),
    actionToUrl: ({ values }) => ({
        setProperties: () => {
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

            if (!objectsEqual(searchParams.properties || {}, values.properties)) {
                actions.setProperties(searchParams.properties || {})
            }
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadPaths,
    }),
})
