import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { toParams, objectsEqual, uuid } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { retentionTableLogicType } from './retentionTableLogicType'
import { RETENTION_FIRST_TIME, RETENTION_RECURRING } from 'lib/constants'
import { actionsModel } from '~/models/actionsModel'
import { ActionType, InsightLogicProps, FilterType, ViewType } from '~/types'
import {
    RetentionTablePayload,
    RetentionTrendPayload,
    RetentionTablePeoplePayload,
    RetentionTrendPeoplePayload,
} from 'scenes/retention/types'
import { dashboardsModel } from '~/models/dashboardsModel'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'

export const dateOptions = ['Hour', 'Day', 'Week', 'Month']

export const retentionOptions = {
    [`${RETENTION_FIRST_TIME}`]: 'First Time',
    [`${RETENTION_RECURRING}`]: 'Recurring',
}

export const retentionOptionDescriptions = {
    [`${RETENTION_RECURRING}`]: 'A user will belong to any cohort where they have performed the event in its Period 0.',
    [`${RETENTION_FIRST_TIME}`]:
        'A user will only belong to the cohort for which they performed the event for the first time.',
}

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

export const retentionTableLogic = kea<retentionTableLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps(DEFAULT_RETENTION_LOGIC_KEY),

    connect: {
        values: [actionsModel, ['actions']],
    },
    actions: () => ({
        setFilters: (filters: Partial<FilterType>) => ({ filters }),
        loadMorePeople: true,
        updatePeople: (people) => ({ people }),
        updateRetention: (retention: RetentionTablePayload[] | RetentionTrendPayload[]) => ({ retention }),
        clearPeople: true,
        clearRetention: true,
        setCachedResults: (filters: Partial<FilterType>, results: any) => ({ filters, results }),
    }),
    loaders: ({ values, props }) => ({
        results: {
            __default: [] as RetentionTablePayload[] | RetentionTrendPayload[],
            setCachedResults: ({ results }) => {
                return results
            },
            loadResults: async (refresh = false, breakpoint) => {
                if (!refresh && (props.cachedResults || props.preventLoading) && values.filters === props.filters) {
                    return props.cachedResults
                }
                const queryId = uuid()
                const dashboardItemId = props.dashboardItemId
                insightLogic(props).actions.startQuery(queryId)
                if (dashboardItemId) {
                    dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, true, null)
                }

                let res
                const urlParams = toParams({ ...values.filters, ...(refresh ? { refresh: true } : {}) })
                try {
                    res = await api.get(`api/insight/retention/?${urlParams}`)
                } catch (e) {
                    breakpoint()
                    insightLogic(props).actions.endQuery(queryId, ViewType.RETENTION, null, e)
                    if (dashboardItemId) {
                        dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, false, null)
                    }
                    return []
                }
                breakpoint()
                insightLogic(props).actions.endQuery(queryId, ViewType.RETENTION, res.last_refresh)
                if (dashboardItemId) {
                    dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, false, res.last_refresh)
                }

                return res.result
            },
        },
        people: {
            __default: {} as RetentionTablePeoplePayload | RetentionTrendPeoplePayload,
            loadPeople: async (rowIndex: number) => {
                const urlParams = toParams({ ...values.filters, selected_interval: rowIndex })
                const res = await api.get(`api/person/retention/?${urlParams}`)
                return res
            },
        },
    }),
    reducers: ({ props }) => ({
        filters: [
            (state: any) => cleanFilters(props.filters || router.selectors.searchParams(state)),
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
        afterMount: () => {
            if (props.dashboardItemId) {
                // loadResults gets called in urlToAction for non-dashboard insights
                actions.loadResults()
            }
        },
    }),
    actionToUrl: ({ props, values }) => ({
        setFilters: () => {
            if (props.syncWithUrl) {
                return ['/insights', values.filters, router.values.hashParams, { replace: true }]
            }
        },
        setProperties: () => {
            if (props.syncWithUrl) {
                return ['/insights', values.filters, router.values.hashParams, { replace: true }]
            }
        },
    }),
    urlToAction: ({ actions, values, props }) => ({
        '/insights': ({}, searchParams) => {
            if (props.syncWithUrl && searchParams.insight === ViewType.RETENTION) {
                const cleanSearchParams = cleanFilters(searchParams)
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
            insightLogic(props).actions.setFilters(values.filters)
            actions.loadResults()
        },
        loadResultsSuccess: async () => {
            actions.clearPeople()
            insightLogic(props).actions.fetchedResults(values.filters)
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
