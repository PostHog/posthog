import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { retentionTableLogicType } from './retentionTableLogicType'
import { ACTIONS_LINE_GRAPH_LINEAR, ACTIONS_TABLE, RETENTION_FIRST_TIME, RETENTION_RECURRING } from 'lib/constants'
import { actionsModel } from '~/models/actionsModel'
import { ActionType, InsightLogicProps, FilterType, InsightType } from '~/types'
import {
    RetentionTablePayload,
    RetentionTrendPayload,
    RetentionTablePeoplePayload,
    RetentionTrendPeoplePayload,
} from 'scenes/retention/types'
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
    path: (key) => ['scenes', 'retention', 'retentionTableLogic', key],
    connect: (props: InsightLogicProps) => ({
        values: [insightLogic(props), ['filters', 'insight', 'insightLoading'], actionsModel, ['actions']],
        actions: [insightLogic(props), ['loadResultsSuccess']],
    }),
    actions: () => ({
        setFilters: (filters: Partial<FilterType>) => ({ filters }),
        setRetentionReference: (retentionReference: FilterType['retention_reference']) => ({ retentionReference }),
        loadMorePeople: true,
        updatePeople: (people) => ({ people }),
        clearPeople: true,
    }),
    loaders: ({ values }) => ({
        people: {
            __default: {} as RetentionTablePeoplePayload | RetentionTrendPeoplePayload,
            loadPeople: async (rowIndex: number) => {
                const urlParams = toParams({ ...values.filters, selected_interval: rowIndex })
                const res = await api.get(`api/person/retention/?${urlParams}`)
                return res
            },
        },
    }),
    reducers: {
        people: {
            clearPeople: () => ({}),
            updatePeople: (_, { people }) => people,
        },
        loadingMore: [
            false,
            {
                loadMorePeople: () => true,
                updatePeople: () => false,
            },
        ],
    },
    selectors: {
        loadedFilters: [
            (s) => [s.insight],
            ({ filters }): Partial<FilterType> => (filters?.insight === InsightType.RETENTION ? filters ?? {} : {}),
        ],
        results: [
            (s) => [s.insight],
            ({ filters, result }): RetentionTablePayload[] | RetentionTrendPayload[] => {
                return filters?.insight === InsightType.RETENTION &&
                    result &&
                    (result.length === 0 ||
                        (!result[0].values && filters.display === ACTIONS_LINE_GRAPH_LINEAR) ||
                        (result[0].values && filters.display === ACTIONS_TABLE))
                    ? result
                    : []
            },
        ],
        trendSeries: [
            (s) => [s.insight, s.retentionReference],
            ({ result }, retentionReference): RetentionTrendPayload[] => {
                // If the retention reference option is specified as previous,
                // then translate retention rates to relative to previous,
                // otherwise, just use what the result was originally.
                if (retentionReference !== 'previous') {
                    return result
                }

                return (result as RetentionTrendPayload[]).map((series) => ({
                    ...series,
                    data: series.data
                        // Zip together the current a previous values, filling
                        // in with 100 for the first index
                        .map((value, index) => [value, [100].concat(series.data)[index]])
                        // map values to percentage of previous
                        .map(([value, previous]) => (100 * value) / previous),
                }))
            },
        ],
        resultsLoading: [(s) => [s.insightLoading], (insightLoading) => insightLoading],
        actionsLookup: [
            (s) => [s.actions],
            (actions: ActionType[]) => Object.assign({}, ...actions.map((action) => ({ [action.id]: action.name }))),
        ],
        actionFilterTargetEntity: [(s) => [s.filters], (filters) => ({ events: [filters.target_entity] })],
        actionFilterReturningEntity: [(s) => [s.filters], (filters) => ({ events: [filters.returning_entity] })],
        retentionReference: [
            (selectors) => [selectors.filters],
            ({ retention_reference = 'total' }) => retention_reference,
        ],
    },
    listeners: ({ actions, values, props }) => ({
        setProperties: ({ properties }) => {
            insightLogic(props).actions.setFilters(cleanFilters({ ...values.filters, properties }, values.filters))
        },
        setFilters: ({ filters }) => {
            insightLogic(props).actions.setFilters(cleanFilters({ ...values.filters, ...filters }, values.filters))
        },
        setRetentionReference: ({ retentionReference }) => {
            actions.setFilters({
                ...values.filters,
                // NOTE: we use lower case here to accommodate the expected
                // casing of the server
                retention_reference: retentionReference,
            })
        },
        loadResultsSuccess: async () => {
            actions.clearPeople()
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
