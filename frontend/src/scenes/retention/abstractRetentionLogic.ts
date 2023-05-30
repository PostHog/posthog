import { kea } from 'kea'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { InsightLogicProps } from '~/types'

import type { abstractRetentionLogicType } from './abstractRetentionLogicType'
import { retentionLogic } from './retentionLogic'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

export const abstractRetentionLogic = kea<abstractRetentionLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps(DEFAULT_RETENTION_LOGIC_KEY),
    path: (key) => ['scenes', 'retention', 'abstractRetentionLogic', key],
    connect: (props: InsightLogicProps) => ({
        values: [retentionLogic(props), ['filters'], insightVizDataLogic(props), ['querySource']],
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
    },
})
