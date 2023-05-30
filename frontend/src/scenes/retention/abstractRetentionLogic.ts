import { kea } from 'kea'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { RetentionTablePayload } from 'scenes/retention/types'
import { InsightLogicProps } from '~/types'

import type { abstractRetentionLogicType } from './abstractRetentionLogicType'
import { retentionLogic } from './retentionLogic'
import { DateRange, BreakdownFilter, RetentionFilter } from '~/queries/schema'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

export const abstractRetentionLogic = kea<abstractRetentionLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps(DEFAULT_RETENTION_LOGIC_KEY),
    path: (key) => ['scenes', 'retention', 'abstractRetentionLogic', key],
    connect: (props: InsightLogicProps) => ({
        values: [
            retentionLogic(props),
            ['filters', 'results as retentionResults'],
            insightVizDataLogic(props),
            [
                'querySource',
                'retentionFilter as dataExplorationRetentionFilter',
                'dateRange as dataExplorationDateRange',
                'breakdown as dataExplorationBreakdown',
            ],
        ],
    }),
    selectors: {
        apiFilters: [
            (s) => [s.filters, s.querySource],
            (filters, querySource) => {
                if (querySource) {
                    return queryNodeToFilter(querySource)
                }

                return filters
            },
        ],
        retentionFilter: [
            (s) => [s.filters, s.dataExplorationRetentionFilter],
            (dataExplorationRetentionFilter): RetentionFilter => {
                return dataExplorationRetentionFilter || {}
            },
        ],
        dateRange: [
            (s) => [s.filters, s.dataExplorationDateRange],
            (dataExplorationDateRange): DateRange => {
                return dataExplorationDateRange || {}
            },
        ],
        breakdown: [
            (s) => [s.filters, s.dataExplorationBreakdown],
            (dataExplorationBreakdown): BreakdownFilter => {
                return dataExplorationBreakdown || {}
            },
        ],
        aggregation: [
            (s) => [s.filters, s.querySource],
            (filters, querySource): { aggregation_group_type_index?: number } => {
                if (querySource) {
                    return {
                        aggregation_group_type_index: querySource.aggregation_group_type_index,
                    }
                }

                return {
                    aggregation_group_type_index: filters.aggregation_group_type_index,
                }
            },
        ],
        results: [(s) => [s.retentionResults], (retentionResults): RetentionTablePayload[] => retentionResults],
    },
})
