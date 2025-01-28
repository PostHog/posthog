import { connect, kea, key, path, props, selectors } from 'kea'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { RetentionTablePayload } from 'scenes/retention/types'

import { isRetentionQuery } from '~/queries/utils'
import { DateMappingOption, InsightLogicProps, RetentionPeriod } from '~/types'

import type { retentionLogicType } from './retentionLogicType'

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

export const retentionLogic = kea<retentionLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_RETENTION_LOGIC_KEY)),
    path((key) => ['scenes', 'retention', 'retentionLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            ['insightQuery', 'insightData', 'querySource', 'dateRange', 'retentionFilter'],
        ],
        actions: [insightVizDataLogic(props), ['updateInsightFilter']],
    })),
    selectors({
        results: [
            (s) => [s.insightQuery, s.insightData],
            (insightQuery, insightData): RetentionTablePayload[] => {
                return isRetentionQuery(insightQuery) ? insightData?.result ?? [] : []
            },
        ],
        period: [
            (s) => [s.retentionFilter],
            (retentionFilter): string => (retentionFilter?.period ?? RetentionPeriod.Day).toLowerCase(),
        ],
        dateMappings: [
            (s) => [s.period],
            (period): DateMappingOption[] => {
                const pluralPeriod = period + 's'
                const periodChar = pluralPeriod.charAt(0)

                return [
                    { key: CUSTOM_OPTION_KEY, values: [] },
                    {
                        key: `Last 7 ${pluralPeriod}`,
                        values: [`-7${periodChar}`],
                    },
                    {
                        key: `Last 14 ${pluralPeriod}`,
                        values: [`-14${periodChar}`],
                    },
                    {
                        key: `Last 30 ${pluralPeriod}`,
                        values: [`-30${periodChar}`],
                    },
                    {
                        key: `Last 90 ${pluralPeriod}`,
                        values: [`-90${periodChar}`],
                    },
                ]
            },
        ],
    }),
])
