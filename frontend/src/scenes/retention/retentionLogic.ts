import { connect, kea, key, path, props, selectors } from 'kea'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { RetentionTablePayload } from 'scenes/retention/types'

import { isRetentionQuery } from '~/queries/utils'
import { InsightLogicProps } from '~/types'

import type { retentionLogicType } from './retentionLogicType'

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

export const retentionLogic = kea<retentionLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_RETENTION_LOGIC_KEY)),
    path((key) => ['scenes', 'retention', 'retentionLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [insightVizDataLogic(props), ['insightQuery', 'insightData', 'querySource']],
    })),
    selectors({
        results: [
            (s) => [s.insightQuery, s.insightData],
            (insightQuery, insightData): RetentionTablePayload[] => {
                return isRetentionQuery(insightQuery) ? insightData?.result ?? [] : []
            },
        ],
    }),
])
