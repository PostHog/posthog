import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { toParams, objectsEqual, uuid } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'
import { retentionTableLogicType } from './retentionTableLogicType'
import { ACTIONS_LINE_GRAPH_LINEAR, ACTIONS_TABLE, RETENTION_FIRST_TIME, RETENTION_RECURRING } from 'lib/constants'
import { actionsModel } from '~/models/actionsModel'
import { ActionType, FilterType, ViewType } from '~/types'
import {
    RetentionTablePayload,
    RetentionTrendPayload,
    RetentionTablePeoplePayload,
    RetentionTrendPeoplePayload,
} from 'scenes/retention/types'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { dashboardsModel } from '~/models/dashboardsModel'

export const dateOptions = ['Hour', 'Day', 'Week', 'Month']

export const retentionOptions = {
    [`${RETENTION_FIRST_TIME}`]: 'First Time',
    [`${RETENTION_RECURRING}`]: 'Recurring',
}

export const retentionOptionDescriptions = {
    [`${RETENTION_RECURRING}`]: 'A user will belong to any cohort where they have performed the event in its Period 0.',
    [`${RETENTION_FIRST_TIME}`]: 'A user will only belong to the cohort for which they performed the event for the first time.',
}

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'
export function defaultFilters(filters: Record<string, any>): Record<string, any> {
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
        properties: filters.properties || [],
        ...(filters.filter_test_accounts ? { filter_test_accounts: filters.filter_test_accounts } : {}),
        insight: ViewType.RETENTION,
    }
}

export const retentionTableLogic = kea<retentionTableLogicType>({
    key: (props) => {
        return props.dashboardItemId || DEFAULT_RETENTION_LOGIC_KEY
    },
    loaders: ({ values, props }) => ({
        results: {
            __default: [] as RetentionTablePayload[] | RetentionTrendPayload[],
            loadResults: async (refresh = false, breakpoint) => {
                if (!refresh && (props.cachedResults || props.preventLoading) && values.filters === props.filters) {
                    return props.cachedResults
                }
                const queryId = uuid()
                const dashboardItemId = props.dashboardItemId as number | undefined
                insightLogic.actions.startQuery(queryId)
                dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, true, null)

                let res
                const urlParams = toParams({ ...values.filters, ...(refresh ? { refresh: true } : {}) })
                try {
                    res = await api.get(`api/insight/retention/?${urlParams}`)
                } catch (e) {
                    breakpoint()
                    insightLogic.actions.endQuery(queryId, ViewType.RETENTION, null, e)
                    dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, false, null)
                    return []
                }
                breakpoint()
                insightLogic.actions.endQuery(queryId, ViewType.RETENTION, res.last_refresh)
                dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, false, res.last_refresh)

                return res.result
            },
        },
        people: {
            __default: {} as RetentionTablePeoplePayload | RetentionTrendPeoplePayload,
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
        actions: [insightHistoryLogic, ['createInsight']],
        values: [actionsModel, ['actions']],
    },
    actions: () => ({
        // TODO: This needs to be properly typed with `FilterType`. N.B. We're currently mixing snake_case and pascalCase attribute names.
        setFilters: (filters: Record<string, any>) => ({ filters }),
        loadMorePeople: true,
        updatePeople: (people) => ({ people }),
        updateRetention: (retention: RetentionTablePayload[] | RetentionTrendPayload[]) => ({ retention }),
        clearPeople: true,
        clearRetention: true,
    }),
    reducers: ({ props }) => ({
        filters: [
            props.filters
                ? defaultFilters(props.filters as Record<string, any>)
                : (state) => defaultFilters(router.selectors.searchParams(state)),
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
        actionFilterTargetEntity: [(s) => [s.filters], (filters) => ({ events: [filters.target_entity] })],
        actionFilterReturningEntity: [(s) => [s.filters], (filters) => ({ events: [filters.returning_entity] })],
    },
    events: ({ actions, props }) => ({
        afterMount: () => props.dashboardItemId && actions.loadResults(),
    }),
    actionToUrl: ({ props, values }) => ({
        setFilters: () => {
            if (props.dashboardItemId) {
                return // don't use the URL if on the dashboard
            }
            return ['/insights', values.filters, router.values.hashParams, { replace: true }]
        },
        setProperties: () => {
            if (props.dashboardItemId) {
                return // don't use the URL if on the dashboard
            }
            return ['/insights', values.filters, router.values.hashParams, { replace: true }]
        },
    }),
    urlToAction: ({ actions, values, key }) => ({
        '/insights': ({}, searchParams: Record<string, any>) => {
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
            actions.loadResults()
        },
        setFilters: () => {
            actions.loadResults()
        },
        loadResults: () => {
            actions.clearPeople()
            insightLogic.actions.setAllFilters(values.filters)
            if (!props.dashboardItemId) {
                if (!insightLogic.values.insight.id) {
                    actions.createInsight(values.filters)
                } else {
                    insightLogic.actions.updateInsightFilters(values.filters)
                }
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
        [dashboardItemsModel.actionTypes.refreshAllDashboardItems]: (filters: FilterType) => {
            if (props.dashboardItemId) {
                actions.setFilters(filters)
            }
        },
    }),
})
