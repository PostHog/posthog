import { kea } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { isRetentionFilter } from 'scenes/insights/sharedUtils'
import { RetentionTablePayload } from 'scenes/retention/types'
import { InsightLogicProps, InsightType, RetentionFilterType } from '~/types'

import type { retentionLogicType } from './retentionLogicType'

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

export const retentionLogic = kea<retentionLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps(DEFAULT_RETENTION_LOGIC_KEY),
    path: (key) => ['scenes', 'retention', 'retentionLogic', key],
    connect: (props: InsightLogicProps) => ({
        values: [insightLogic(props), ['filters as inflightFilters', 'insight', 'insightLoading']],
    }),
    actions: () => ({
        setFilters: (filters: Partial<RetentionFilterType>) => ({ filters }),
    }),
    selectors: {
        filters: [
            (s) => [s.inflightFilters],
            (inflightFilters): Partial<RetentionFilterType> =>
                inflightFilters && isRetentionFilter(inflightFilters) ? inflightFilters : {},
        ],
        results: [
            // Take the insight result, and cast it to `RetentionTablePayload[]`
            (s) => [s.insight],
            ({ filters, result }): RetentionTablePayload[] => {
                return filters?.insight === InsightType.RETENTION ? result ?? [] : []
            },
        ],
        resultsLoading: [(s) => [s.insightLoading], (insightLoading) => insightLoading],
    },
    listeners: ({ values, props }) => ({
        setFilters: ({ filters }) => {
            insightLogic(props).actions.setFilters(cleanFilters({ ...values.filters, ...filters }, values.filters))
        },
    }),
})
