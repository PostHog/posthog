import { connect, kea, key, path, props, selectors } from 'kea'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { dayjs } from 'lib/dayjs'
import { formatDateRange } from 'lib/utils'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { ProcessedRetentionPayload } from 'scenes/retention/types'

import { RetentionFilter, RetentionResult } from '~/queries/schema/schema-general'
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
        actions: [insightVizDataLogic(props), ['updateInsightFilter', 'updateDateRange']],
    })),
    selectors({
        results: [
            (s) => [s.insightQuery, s.insightData, s.retentionFilter],
            (insightQuery, insightData, retentionFilter): ProcessedRetentionPayload[] => {
                const rawResults = isRetentionQuery(insightQuery) ? insightData?.result ?? [] : []

                const results: ProcessedRetentionPayload[] = rawResults.map((result: RetentionResult) => ({
                    ...result,
                    values: result.values.map((value, index) => {
                        const totalCount = result.values[0]['count']
                        const previousCount = index > 0 ? result.values[index - 1]['count'] : totalCount
                        const referenceCount =
                            retentionFilter?.retentionReference === 'previous' ? previousCount : totalCount
                        const percentage = referenceCount > 0 ? (value['count'] / referenceCount) * 100 : 0

                        const periodUnit = (
                            retentionFilter?.period ?? RetentionPeriod.Day
                        ).toLowerCase() as dayjs.UnitTypeLong
                        const cellDate = dayjs.utc(result.date).add(index, periodUnit)
                        const now = dayjs.utc()

                        return {
                            ...value,
                            percentage,
                            cellDate,
                            isCurrentPeriod: cellDate.isSame(now, periodUnit),
                            isFuture: cellDate.isAfter(now),
                        }
                    }),
                }))

                // Filter out future values for now
                return results.map((result) => ({
                    ...result,
                    values: result.values.filter((value) => !value.isFuture),
                }))
            },
        ],
        dateMappings: [
            (s) => [s.retentionFilter],
            (retentionFilter: RetentionFilter): DateMappingOption[] => {
                const pluralPeriod = (retentionFilter?.period ?? RetentionPeriod.Day).toLowerCase() + 's'
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
                    {
                        key: 'Year to date',
                        values: ['yStart'],
                        getFormattedDate: (date: dayjs.Dayjs): string =>
                            formatDateRange(date.startOf('y'), date.endOf('d')),
                        defaultInterval: 'month',
                    },
                    {
                        key: 'All time',
                        values: ['all'],
                        defaultInterval: 'month',
                    },
                ]
            },
        ],
    }),
])
