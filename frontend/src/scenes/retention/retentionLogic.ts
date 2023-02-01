import { kea } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { isRetentionFilter } from 'scenes/insights/sharedUtils'
import { RetentionTablePayload } from 'scenes/retention/types'
import { actionsModel } from '~/models/actionsModel'
import { ActionType, InsightLogicProps, InsightType, RetentionFilterType } from '~/types'

import type { retentionLogicType } from './retentionLogicType'

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

export const retentionLogic = kea<retentionLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps(DEFAULT_RETENTION_LOGIC_KEY),
    path: (key) => ['scenes', 'retention', 'retentionLogic', key],
    connect: (props: InsightLogicProps) => ({
        values: [
            insightLogic(props),
            ['filters as inflightFilters', 'insight', 'insightLoading'],
            actionsModel,
            ['actions'],
        ],
    }),
    actions: () => ({
        setFilters: (filters: Partial<RetentionFilterType>) => ({ filters }),
        setRetentionReference: (retentionReference: RetentionFilterType['retention_reference']) => ({
            retentionReference,
        }),
    }),
    selectors: {
        filters: [
            (s) => [s.inflightFilters],
            (inflightFilters): Partial<RetentionFilterType> =>
                inflightFilters && isRetentionFilter(inflightFilters) ? inflightFilters : {},
        ],
        loadedFilters: [
            (s) => [s.insight],
            ({ filters }): Partial<RetentionFilterType> => (filters && isRetentionFilter(filters) ? filters : {}),
        ],
        results: [
            // Take the insight result, and cast it to `RetentionTablePayload[]`
            (s) => [s.insight],
            ({ filters, result }): RetentionTablePayload[] => {
                return filters?.insight === InsightType.RETENTION ? result ?? [] : []
            },
        ],
        resultsLoading: [(s) => [s.insightLoading], (insightLoading) => insightLoading],
        actionsLookup: [
            (s) => [s.actions],
            (actions: ActionType[]) => Object.assign({}, ...actions.map((action) => ({ [action.id]: action.name }))),
        ],
        retentionReference: [
            (selectors) => [selectors.filters],
            ({ retention_reference }) => retention_reference ?? 'total',
        ],
    },
    listeners: ({ actions, values, props }) => ({
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
    }),
})
