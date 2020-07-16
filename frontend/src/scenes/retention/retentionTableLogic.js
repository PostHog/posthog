import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { toParams, objectsEqual } from 'lib/utils'

export const retentionTableLogic = kea({
    loaders: (props) => ({
        retention: {
            __default: {},
            loadRetention: async () => {
                const urlParams = toParams({ properties: props.values.properties })
                return await api.get(`api/action/retention/?${urlParams}`)
            },
        },
    }),
    actions: () => ({
        setProperties: (properties) => ({ properties }),
        setFilters: (filters) => ({ filters }),
    }),
    reducers: () => ({
        initialPathname: [(state) => router.selectors.location(state).pathname, { noop: (a) => a }],
        properties: [
            [],
            {
                setProperties: (_, { properties }) => properties,
            },
        ],
        filters: [
            {},
            {
                setFilters: (_, { filters }) => filters,
            },
        ],
    }),
    selectors: ({ selectors }) => ({
        propertiesForUrl: [
            () => [selectors.properties],
            (properties) => {
                if (Object.keys(properties).length > 0) {
                    return { properties }
                } else {
                    return ''
                }
            },
        ],
        startEntity: [
            () => [selectors.filters],
            (filters) => {
                const result = Object.keys(filters).reduce(function (r, k) {
                    return r.concat(filters[k])
                }, [])

                return result[0] || null
            },
        ],
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadRetention,
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
    listeners: ({ actions }) => ({
        setProperties: () => actions.loadRetention(),
    }),
})
