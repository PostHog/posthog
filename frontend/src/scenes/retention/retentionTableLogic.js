import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { toParams, objectsEqual } from 'lib/utils'
import moment from 'moment'

export const dateOptions = {
    h: 'Hour',
    d: 'Day',
    w: 'Week',
}

export const retentionTableLogic = kea({
    loaders: ({ values }) => ({
        retention: {
            __default: {},
            loadRetention: async () => {
                let params = { properties: values.properties }
                if (values.selectedDate) params['date_from'] = values.selectedDate.toISOString()
                if (values.period) params['period'] = dateOptions[values.period]
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
    actions: () => ({
        setProperties: (properties) => ({ properties }),
        dateChanged: (date) => ({ date }),
        setPeriod: (period) => ({ period }),
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
        selectedDate: [moment().subtract(11, 'days').startOf('day'), { dateChanged: (_, { date }) => date }],
        period: ['d', { setPeriod: (_, { period }) => period }],
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
            () => [selectors.properties, selectors.selectedDate, selectors.period],
            (properties, selectedDate, period) => {
                let result = {}
                if (Object.keys(properties).length > 0) {
                    result['properties'] = properties
                }
                if (selectedDate) {
                    result['date_from'] = selectedDate.format('YYYY-MM-DD')
                }
                if (selectedDate) {
                    result['period'] = period
                }

                return result
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
    actionToUrl: ({ values }) => ({
        setProperties: () => {
            return [router.values.location.pathname, values.propertiesForUrl]
        },
        dateChanged: () => {
            return [router.values.location.pathname, values.propertiesForUrl]
        },
        setPeriod: () => {
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
            if (!objectsEqual(searchParams.date_from || {}, values.selectedDate.format('YYYY-MM-DD'))) {
                searchParams.date_from && actions.dateChanged(moment(searchParams.date_from))
            }
            if (searchParams.period !== values.period) {
                searchParams.period && actions.setPeriod(searchParams.period)
            }
        },
    }),
    listeners: ({ actions, values }) => ({
        setProperties: () => actions.loadRetention(),
        dateChanged: () => {
            actions.loadRetention()
        },
        setPeriod: () => {
            actions.loadRetention()
        },
        setFilters: () => actions.loadRetention(),
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
