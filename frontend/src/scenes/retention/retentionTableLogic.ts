import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { toParams, objectsEqual } from 'lib/utils'
import { ViewType, insightLogic } from 'scenes/insights/insightLogic'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'
import { Moment } from 'moment'
import { retentionTableLogicType } from 'types/scenes/retention/retentionTableLogicType'
import { ACTIONS_LINE_GRAPH_LINEAR, ACTIONS_TABLE } from 'lib/constants'

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
        date_to: filters.date_to,
        period: filters.period || 'd',
        display: filters.display || 'ActionsTable',
    }
}

function toUrlParams(values: Record<string, unknown>, extraVals?: Record<string, unknown>): string {
    let params: Record<string, any> = { ...values.filters }
    params['properties'] = values.properties
    if (values.period) {
        params['period'] = dateOptions[values.period]
    }
    if (values.startEntity) {
        params['target_entity'] = values.startEntity
    }
    if (values.retentionType) {
        params['retention_type'] = values.retentionType
    }
    if (values.returningEntity) {
        params['actions'] = Array.isArray(values.filters.returningEntity.actions)
            ? values.filters.returningEntity.actions
            : []
        params['events'] = Array.isArray(values.filters.returningEntity.events)
            ? values.filters.returningEntity.events
            : []
    }
    params = {
        ...params,
        ...extraVals,
    }
    const urlParams = toParams(params)
    return urlParams
}

export const retentionTableLogic = kea<retentionTableLogicType<Moment>>({
    key: (props) => {
        return props.dashboardItemId || DEFAULT_RETENTION_LOGIC_KEY
    },
    loaders: ({ values }) => ({
        retention: {
            __default: ({} as Record<string, unknown>) || Array,
            loadRetention: async (_: any, breakpoint) => {
                const urlParams = toUrlParams(values)
                const res = await api.get(`api/insight/retention/?${urlParams}`)
                breakpoint()
                return res
            },
        },
        people: {
            __default: {} as Record<string, unknown>,
            loadPeople: async (rowIndex) => {
                if (values.filters.display === ACTIONS_LINE_GRAPH_LINEAR) {
                    const urlParams = toUrlParams(values, { selected_interval: rowIndex })
                    const res = await api.get(`api/person/retention/?${urlParams}`)

                    return res
                } else {
                    const urlParams = toUrlParams(values, { selected_interval: rowIndex })
                    const res = await api.get(`api/person/retention/?${urlParams}`)

                    return res
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
        loadMorePeople: true,
        updatePeople: (people) => ({ people }),
        updateRetention: (retention) => ({ retention }),
        clearPeople: true,
        clearRetention: true,
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
                      returningEntity: props.filters.returningEntity || {
                          events: [{ id: '$pageview', type: 'events', name: '$pageview' }],
                          actions: [],
                      },
                      date_to: props.filters.date_to,
                      period: props.filters.period || 'd',
                      retentionType: props.filters.retentionType || RETENTION_FIRST_TIME,
                      display: props.filters.display || ACTIONS_TABLE,
                  }
                : (state) => cleanFilters(router.selectors.searchParams(state)),
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
        people: {
            clearPeople: () => ({}),
            updatePeople: (_, { people }) => people,
        },
        retention: {
            updateRetention: (_, { retention }) => retention,
            clearRetention: () => ({}),
        },
        loadingMore: [
            false,
            {
                loadMorePeople: () => true,
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
    actionToUrl: ({ props, values }) => ({
        setFilters: () => {
            if (props.dashboardItemId) {
                return // don't use the URL if on the dashboard
            }
            return ['/insights', values.propertiesForUrl, router.values.hashParams]
        },
        setProperties: () => {
            if (props.dashboardItemId) {
                return // don't use the URL if on the dashboard
            }
            return ['/insights', values.propertiesForUrl, router.values.hashParams]
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

                if (cleanSearchParams.display !== cleanedFilters.display) {
                    actions.clearRetention()
                    actions.clearPeople()
                }
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
        loadMorePeople: async () => {
            if (values.people.next) {
                const peopleResult = await api.get(values.people.next)
                const newPeople = {
                    result: [...values.people.result, ...peopleResult['result']],
                    next: peopleResult['next'],
                }
                actions.updatePeople(newPeople)
            }
        },
    }),
})
