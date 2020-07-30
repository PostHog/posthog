import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { toParams, objectsEqual } from 'lib/utils'
import { ViewType, insightLogic } from 'scenes/insights/insightLogic'

function cleanRetentionParams(filters, properties) {
    return {
        ...filters,
        properties: properties,
        insight: ViewType.RETENTION,
    }
}

export const retentionTableLogic = kea({
    loaders: ({ values }) => ({
        retention: {
            __default: {},
            loadRetention: async () => {
                let params = {}
                params['properties'] = values.properties
                if (values.startEntity) params['start_entity'] = values.startEntity
                const urlParams = toParams(params)
                return await api.get(`api/action/retention/?${urlParams}`)
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
    connect: {
        actions: [insightLogic, ['setAllFilters']],
    },
    actions: () => ({
        setProperties: (properties) => ({ properties }),
        setFilters: (filters) => ({ filters }),
        loadMore: (selectedIndex) => ({ selectedIndex }),
        loadMorePeople: (selectedIndex, peopleIds) => ({ selectedIndex, peopleIds }),
        updatePeople: (selectedIndex, people) => ({ selectedIndex, people }),
        updateRetention: (retention) => ({ retention }),
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
        startEntity: [
            () => [selectors.filters],
            (filters) => {
                const result = Object.keys(filters).reduce(function (r, k) {
                    return r.concat(filters[k])
                }, [])

                return result[0] || { id: '$pageview', type: 'events', name: '$pageview' }
            },
        ],
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadRetention,
    }),
    actionToUrl: ({ actions, values }) => ({
        [actions.setFilters]: () => {
            return ['/insights', { target: values.startEntity, insight: ViewType.RETENTION }]
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
            if (searchParams.target && values.startEntity.id !== searchParams.target?.id) {
                actions.setFilters({
                    [`${searchParams.target.type}`]: [searchParams.target],
                })
            }
        },
    }),
    listeners: ({ actions, values }) => ({
        setProperties: () => {
            actions.loadRetention()
            actions.setAllFilters(cleanRetentionParams({ target: values.startEntity }, values.properties))
        },
        setFilters: () => {
            actions.loadRetention()
            actions.setAllFilters(cleanRetentionParams({ target: values.startEntity }, values.properties))
        },
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
