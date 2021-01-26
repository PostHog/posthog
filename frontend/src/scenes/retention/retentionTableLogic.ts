import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { toParams, objectsEqual } from 'lib/utils'
import { ViewType, insightLogic } from 'scenes/insights/insightLogic'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'
import { Moment } from 'moment'
import { retentionTableLogicType } from './retentionTableLogicType'
import { ACTIONS_LINE_GRAPH_LINEAR, ACTIONS_TABLE } from 'lib/constants'
import { actionsModel } from '~/models'
import { ActionType } from '~/types'

export const dateOptions = ['Hour', 'Day', 'Week', 'Month']

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
function defaultFilters(filters: Record<string, any>): Record<string, any> {
    return {
        target_entity: filters.target_entity || {
            id: '$pageview',
            name: '$pageview',
            type: 'events',
        },
        returning_entity: filters.returning_entity || { id: '$pageview', type: 'events', name: '$pageview' },
        date_to: filters.date_to,
        period: filters.period || 'Day',
        retention_type: filters.retention_type || RETENTION_FIRST_TIME,
        display: filters.display || ACTIONS_TABLE,
    }
}

export const retentionTableLogic = kea<retentionTableLogicType<Moment>>({
    key: (props) => {
        return props.dashboardItemId || DEFAULT_RETENTION_LOGIC_KEY
    },
    loaders: ({ values, props }) => ({
        results: {
            __default: [],
            loadResults: async (refresh = false, breakpoint) => {
                if (!refresh && (props.cachedResults || props.preventLoading)) {
                    return props.cachedResults
                }
                insightLogic.actions.startQuery()
                let res
                const urlParams = toParams({ ...values.filters, ...(refresh ? { refresh: true } : {}) })
                try {
                    res = await api.get(`api/insight/retention/?${urlParams}`)
                } catch (e) {
                    insightLogic.actions.endQuery(ViewType.RETENTION, e)
                    return []
                }
                breakpoint()
                insightLogic.actions.endQuery(ViewType.RETENTION)
                return res.data
            },
        },
        people: {
            __default: {} as Record<string, unknown>,
            loadPeople: async (rowIndex) => {
                if (values.filters.display === ACTIONS_LINE_GRAPH_LINEAR) {
                    const urlParams = toParams({ ...values.filters, selected_interval: rowIndex })
                    const res = await api.get(`api/person/retention/?${urlParams}`)

                    return res
                } else {
                    const urlParams = toParams({ ...values.filters, selected_interval: rowIndex })
                    const res = await api.get(`api/person/retention/?${urlParams}`)

                    return res
                }
            },
        },
    }),
    connect: {
        actions: [insightLogic, ['setAllFilters'], insightHistoryLogic, ['createInsight']],
        values: [actionsModel, ['actions']],
    },
    actions: () => ({
        setFilters: (filters) => ({ filters }),
        loadMorePeople: true,
        updatePeople: (people) => ({ people }),
        updateRetention: (retention) => ({ retention }),
        clearPeople: true,
        clearRetention: true,
    }),
    reducers: ({ props }) => ({
        filters: [
            props.filters
                ? defaultFilters(props.filters as Record<string, any>)
                : (state) => defaultFilters(router.selectors.searchParams(state)) as Record<string, any>,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
        people: {
            clearPeople: () => ({}),
            updatePeople: (_, { people }) => people,
        },
        results: {
            updateRetention: (_, { retention }) => retention,
            clearRetention: () => [],
        },
        loadingMore: [
            false,
            {
                loadMorePeople: () => true,
                updatePeople: () => false,
            },
        ],
    }),
    selectors: {
        actionsLookup: [
            (selectors) => [(selectors as any).actions],
            (actions: ActionType[]) => Object.assign({}, ...actions.map((action) => ({ [action.id]: action.name }))),
        ],
    },
    events: ({ actions, props }) => ({
        afterMount: () => props.dashboardItemId && actions.loadResults(),
    }),
    actionToUrl: ({ props, values }) => ({
        setFilters: () => {
            if (props.dashboardItemId) {
                return // don't use the URL if on the dashboard
            }
            return ['/insights', values.filters, router.values.hashParams]
        },
        setProperties: () => {
            if (props.dashboardItemId) {
                return // don't use the URL if on the dashboard
            }
            return ['/insights', values.filters, router.values.hashParams]
        },
    }),
    urlToAction: ({ actions, values, key }) => ({
        '/insights': (_: any, searchParams: Record<string, any>) => {
            if (searchParams.insight === ViewType.RETENTION) {
                if (key != DEFAULT_RETENTION_LOGIC_KEY) {
                    return
                }

                const cleanSearchParams = searchParams
                const cleanedFilters = values.filters

                if (cleanSearchParams.display !== cleanedFilters.display) {
                    actions.clearRetention()
                    actions.clearPeople()
                }
                if (!objectsEqual(cleanSearchParams, cleanedFilters)) {
                    actions.setFilters(cleanSearchParams)
                }
            }
        },
    }),
    listeners: ({ actions, values, props }) => ({
        setProperties: () => {
            actions.loadResults(true)
        },
        setFilters: () => {
            actions.loadResults(true)
        },
        loadResults: () => {
            actions.clearPeople()
            actions.setAllFilters(values.filters)
            if (!props.dashboardItemId) {
                actions.createInsight(values.filters)
            }
        },
        loadMorePeople: async () => {
            if (values.people.next) {
                const peopleResult = await api.get(values.people.next)
                const newPeople = {
                    result: [...(values.people.result as Record<string, any>[]), ...peopleResult['result']],
                    next: peopleResult['next'],
                }
                actions.updatePeople(newPeople)
            }
        },
    }),
})
