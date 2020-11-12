import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { toParams, objectsEqual } from 'lib/utils'
import { ViewType, insightLogic } from 'scenes/insights/insightLogic'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'
import moment, { Moment } from 'moment'
import { retentionTableLogicType } from 'types/scenes/retention/retentionTableLogicType'

export const dateOptions = {
    h: 'Hour',
    d: 'Day',
    w: 'Week',
    m: 'Month',
}

const RETENTION_RECURRING = 'retention_recurring'
const RETENTION_FIRST_TIME = 'retention_first_time'

export const retentionOptions = {
    [`${RETENTION_FIRST_TIME}`]: 'First Time',
    [`${RETENTION_RECURRING}`]: 'Recurring',
}

export const retentionOptionDescriptions = {
    [`${RETENTION_RECURRING}`]: 'A user will belong to any cohort where they have performed the event in its Period 0.',
    [`${RETENTION_FIRST_TIME}`]: 'A user will only belong to the cohort for which they performed the event for the first time.',
}

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

function cleanRetentionParams(filters, properties): any {
    return {
        ...filters,
        selectedDate: filters.selectedDate?.format('YYYY-MM-DD HH:00') || moment().format('YYYY-MM-DD HH:00'),
        properties: properties,
        insight: ViewType.RETENTION,
    }
}

function cleanFilters(filters): any {
    return {
        startEntity: filters.startEntity || {
            events: [{ id: '$pageview', name: '$pageview', type: 'events' }],
        },
        returningEntity: filters.returningEntity || {
            events: [{ id: '$pageview', name: '$pageview', type: 'events' }],
        },
        retentionType: filters.retentionType || RETENTION_FIRST_TIME,
        selectedDate: filters.selectedDate ? moment(filters.selectedDate) : moment().startOf('hour'),
        period: filters.period || 'd',
    }
}

export const retentionTableLogic = kea<retentionTableLogicType<Moment>>({
    key: (props) => {
        return props.dashboardItemId || DEFAULT_RETENTION_LOGIC_KEY
    },
    loaders: ({ values }) => ({
        retention: {
            __default: {},
            loadRetention: async (_: any, breakpoint) => {
                const params: Record<string, any> = {}
                params['properties'] = values.properties
                if (values.selectedDate) params['date_to'] = values.selectedDate.toISOString()
                if (values.period) params['period'] = dateOptions[values.period]
                if (values.startEntity) params['target_entity'] = values.startEntity
                if (values.retentionType) params['retention_type'] = values.retentionType
                if (values.returningEntity) {
                    params['actions'] = Array.isArray(values.filters.returningEntity.actions)
                        ? values.filters.returningEntity.actions
                        : []
                    params['events'] = Array.isArray(values.filters.returningEntity.events)
                        ? values.filters.returningEntity.events
                        : []
                }
                const urlParams = toParams(params)
                const res = await api.get(`api/insight/retention/?${urlParams}`)
                breakpoint()
                return res
            },
        },
        people: {
            __default: {},
            loadPeople: async (rowIndex) => {
                const people = values.retention.data[rowIndex].values[0].people

                if (people.length === 0) return []
                const results = (await api.get('api/person/?id=' + people.join(','))).results
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
        actions: [insightLogic, ['setAllFilters'], insightHistoryLogic, ['createInsight']],
    },
    actions: () => ({
        setProperties: (properties) => ({ properties }),
        setFilters: (filters) => ({ filters }),
        loadMore: (selectedIndex) => ({ selectedIndex }),
        loadMorePeople: (selectedIndex, peopleIds) => ({ selectedIndex, peopleIds }),
        updatePeople: (selectedIndex, people) => ({ selectedIndex, people }),
        updateRetention: (retention) => ({ retention }),
        clearPeople: true,
    }),
    reducers: ({ props }) => ({
        initialPathname: [(state) => router.selectors.location(state).pathname, { noop: (a) => a }],
        properties: [
            props.filters
                ? props.filters.properties || []
                : (state) => router.selectors.searchParams(state).properties || [],
            {
                setProperties: (_, { properties }) => properties,
            },
        ],
        filters: [
            props.filters
                ? {
                      startEntity: props.filters.startEntity || {
                          events: [{ id: '$pageview', name: '$pageview', type: 'events' }],
                      },
                      selectedDate: moment(props.filters.selectedDate) || moment().startOf('hour'),
                      returningEntity: props.filters.returningEntity || {
                          events: [{ id: '$pageview', type: 'events', name: '$pageview' }],
                          actions: [],
                      },
                      period: props.filters.period || 'd',
                      retentionType: props.filters.retentionType || RETENTION_FIRST_TIME,
                  }
                : (state) => cleanFilters(router.selectors.searchParams(state)),
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
        people: {
            clearPeople: () => ({}),
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
            () => [selectors.filters, selectors.properties],
            (filters, properties) => {
                return cleanRetentionParams(filters, properties)
            },
        ],
        startEntity: [
            () => [selectors.filters],
            (filters) => {
                const result = Object.keys(filters.startEntity).reduce(function (r, k) {
                    return r.concat(filters.startEntity[k])
                }, [])

                return result[0] || { id: '$pageview', type: 'events', name: '$pageview' }
            },
        ],
        returningEntity: [
            () => [selectors.filters],
            (filters) => {
                const result = Object.keys(filters.returningEntity).reduce(function (r, k) {
                    return r.concat(filters.returningEntity[k])
                }, [])

                return result[0] || { id: '$pageview', type: 'events', name: '$pageview' }
            },
        ],
        selectedDate: [
            () => [selectors.filters],
            (filters) => {
                return filters.selectedDate
            },
        ],
        retentionType: [
            () => [selectors.filters],
            (filters) => {
                return filters.retentionType
            },
        ],
        period: [
            () => [selectors.filters],
            (filters) => {
                return filters.period
            },
        ],
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadRetention,
    }),
    actionToUrl: ({ values }) => ({
        setFilters: () => {
            return ['/insights', values.propertiesForUrl]
        },
        setProperties: () => {
            return ['/insights', values.propertiesForUrl]
        },
    }),
    urlToAction: ({ actions, values, key }) => ({
        '/insights': (_, searchParams: Record<string, any>) => {
            if (searchParams.insight === ViewType.RETENTION) {
                if (key != DEFAULT_RETENTION_LOGIC_KEY) {
                    return
                }
                const cleanSearchParams = cleanFilters(searchParams)
                const cleanedFilters = cleanFilters(values.filters)
                if (!objectsEqual(cleanSearchParams, cleanedFilters)) {
                    actions.setFilters(cleanSearchParams)
                }
                if (!objectsEqual(searchParams.properties, values.properties)) {
                    actions.setProperties(searchParams.properties || [])
                }
            }
        },
    }),
    listeners: ({ actions, values }) => ({
        setProperties: () => {
            actions.loadRetention(true)
        },
        setFilters: () => {
            actions.loadRetention(true)
        },
        loadRetention: () => {
            actions.clearPeople()
            actions.setAllFilters(cleanRetentionParams(values.filters, values.properties))
            actions.createInsight(cleanRetentionParams(values.filters, values.properties))
        },
        loadMore: async ({ selectedIndex }) => {
            let peopleToAdd = []
            for (const [index, { next, offset }] of values.retention.data[selectedIndex].values.entries()) {
                if (next) {
                    const params = toParams({ id: next, offset })
                    const referenceResults = await api.get(`api/person/references/?${params}`)
                    const retentionCopy = { ...values.retention }
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
