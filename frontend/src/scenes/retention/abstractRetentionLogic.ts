import { kea } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { RetentionTablePayload } from 'scenes/retention/types'
import { InsightLogicProps } from '~/types'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'

import type { abstractRetentionLogicType } from './abstractRetentionLogicType'
import { retentionLogic } from './retentionLogic'
import { DateRange, BreakdownFilter, RetentionFilter } from '~/queries/schema'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

// this logic disambiguates between data exploration "queries" and
// regular "filters" for the purposes of feature flag `data-exploration-insights`
export const abstractRetentionLogic = kea<abstractRetentionLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps(DEFAULT_RETENTION_LOGIC_KEY),
    path: (key) => ['scenes', 'retention', 'abstractRetentionLogic', key],
    connect: (props: InsightLogicProps) => ({
        values: [
            insightLogic(props),
            ['isUsingDataExploration'],
            retentionLogic(props),
            ['filters', 'results as retentionResults', 'resultsLoading as retentionResultsLoading'],
            insightDataLogic(props),
            [
                'querySource as dataExplorationQuerySource',
                'retentionFilter as dataExplorationRetentionFilter',
                'breakdown as dataExplorationBreakdown',
                'dateRange as dataExplorationDateRange',
            ],
        ],
    }),
    selectors: {
        apiFilters: [
            (s) => [s.isUsingDataExploration, s.filters, s.dataExplorationQuerySource],
            (isUsingDataExploration, filters, dataExplorationQuerySource) => {
                if (isUsingDataExploration) {
                    return queryNodeToFilter(dataExplorationQuerySource)
                }

                return filters
            },
        ],
        retentionFilter: [
            (s) => [s.isUsingDataExploration, s.filters, s.dataExplorationRetentionFilter],
            (isUsingDataExploration, filters, dataExplorationRetentionFilter): RetentionFilter => {
                if (isUsingDataExploration) {
                    return dataExplorationRetentionFilter || {}
                }

                return {
                    retention_type: filters.retention_type,
                    retention_reference: filters.retention_reference,
                    total_intervals: filters.total_intervals,
                    target_entity: filters.target_entity,
                    returning_entity: filters.returning_entity,
                    period: filters.period,
                }
            },
        ],
        dateRange: [
            (s) => [s.isUsingDataExploration, s.filters, s.dataExplorationDateRange],
            (isUsingDataExploration, filters, dataExplorationDateRange): DateRange => {
                if (isUsingDataExploration) {
                    return dataExplorationDateRange || {}
                }

                return {
                    date_to: filters.date_to,
                    date_from: filters.date_from,
                }
            },
        ],
        breakdown: [
            (s) => [s.isUsingDataExploration, s.filters, s.dataExplorationBreakdown],
            (isUsingDataExploration, filters, dataExplorationBreakdown): BreakdownFilter => {
                if (isUsingDataExploration) {
                    return dataExplorationBreakdown || {}
                }

                return {
                    breakdown_type: filters.breakdown_type,
                    breakdown: filters.breakdown,
                    breakdown_normalize_url: filters.breakdown_normalize_url,
                    breakdowns: filters.breakdowns,
                    breakdown_value: filters.breakdown_value,
                    breakdown_group_type_index: filters.breakdown_group_type_index,
                }
            },
        ],
        aggregation: [
            (s) => [s.isUsingDataExploration, s.filters, s.dataExplorationQuerySource],
            (
                isUsingDataExploration,
                filters,
                dataExplorationQuerySource
            ): { aggregation_group_type_index?: number } => {
                if (isUsingDataExploration) {
                    return {
                        aggregation_group_type_index: dataExplorationQuerySource.aggregation_group_type_index,
                    }
                }

                return {
                    aggregation_group_type_index: filters.aggregation_group_type_index,
                }
            },
        ],
        results: [(s) => [s.retentionResults], (retentionResults): RetentionTablePayload[] => retentionResults],
        resultsLoading: [(s) => [s.retentionResultsLoading], (retentionResultsLoading) => retentionResultsLoading],
    },
})
