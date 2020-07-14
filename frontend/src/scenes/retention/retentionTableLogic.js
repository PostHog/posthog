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
                const result = await api.get(`api/action/retention/?${urlParams}`)
                return result
            },
        },
        people: {
            loadPeople: async (people) => {
                if (people.length === 0) return []
                return (await api.get('api/person/?id=' + people.join(','))).results
            },
        },
    }),
    actions: () => ({
        setProperties: (properties) => ({ properties }),
        loadMore: (selectedIndex) => ({ selectedIndex }),
    }),
    reducers: () => ({
        initialPathname: [(state) => router.selectors.location(state).pathname, { noop: (a) => a }],
        properties: [
            [],
            {
                setProperties: (_, { properties }) => properties,
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
    listeners: ({ actions, values }) => ({
        setProperties: () => actions.loadRetention(),
        loadMore: async ({ selectedIndex }) => {
            await api.get(`api/person/references/${values.retention.data[selectedIndex].values[0].next}`)
        },
    }),
})
