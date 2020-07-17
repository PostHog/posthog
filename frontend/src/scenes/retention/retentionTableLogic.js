import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { toParams, objectsEqual } from 'lib/utils'

export const retentionTableLogic = kea({
    loaders: (props) => ({
        retention: {
            __default: {},
            loadRetention: async () => {
                const urlParams = toParams({ properties: values.properties })
                const result = await api.get(`api/action/retention/?${urlParams}`)
                return result
            },
        },
        people: {
            __default: {},
            loadPeople: async (rowIndex) => {
                const people = values.retention.data[rowIndex].values[0].people

                if (people.length === 0) return []
                let results = (await api.get('api/person/?id=' + people.join(','))).results
                results.sort(function (a, b) {
                    return people.indexOf(a.id) - people.indexOf(b.id)
                })
                return {
                    ...values.people,
                    [`${rowIndex}`]: results,
                }
            },
        },
    }),
    actions: () => ({
        setProperties: (properties) => ({ properties }),
    }),
    reducers: () => ({
        initialPathname: [(state) => router.selectors.location(state).pathname, { noop: (a) => a }],
        properties: [
            [],
            {
                setProperties: (_, { properties }) => properties,
            },
        ],
        people: {
            updatePeople: (state, { selectedIndex, people }) => ({
                ...state,
                [`${selectedIndex}`]: [...state[selectedIndex], ...people],
            }),
        },
        retention: {
            updateRetention: (_, { retention }) => retention,
        },
        loadingMore: [
            false,
            {
                loadMore: () => true,
                updatePeople: () => false,
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
            let peopleToAdd = []
            for (const [index, { next, offset }] of values.retention.data[selectedIndex].values.entries()) {
                if (next) {
                    const params = toParams({ id: next, offset })
                    const referenceResults = await api.get(`api/person/references/?${params}`)
                    let retentionCopy = { ...values.retention }
                    if (referenceResults.offset) {
                        retentionCopy.data[selectedIndex].values[index].offset = referenceResults.offset
                    } else {
                        retentionCopy.data[selectedIndex].values[index].next = null
                    }
                    retentionCopy.data[selectedIndex].values[index].people = [
                        ...retentionCopy.data[selectedIndex].values[index].people,
                        ...referenceResults.result,
                    ]
                    actions.updateRetention(retentionCopy)
                    if (index === 0) peopleToAdd = referenceResults.result
                }
            }

            actions.loadMorePeople(selectedIndex, peopleToAdd)
        },
        loadMorePeople: async ({ selectedIndex, peopleIds }) => {
            if (peopleIds.length === 0) actions.updatePeople(selectedIndex, [])
            const peopleResult = (await api.get('api/person/?id=' + peopleIds.join(','))).results
            peopleResult.sort(function (a, b) {
                return peopleIds.indexOf(a.id) - peopleIds.indexOf(b.id)
            })
            actions.updatePeople(selectedIndex, peopleResult)
        },
    }),
})
