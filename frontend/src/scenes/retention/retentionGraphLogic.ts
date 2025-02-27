import { connect, kea, key, path, props, selectors } from 'kea'
import { dayjs, QUnitType } from 'lib/dayjs'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { ProcessedRetentionPayload, RetentionTrendPayload } from 'scenes/retention/types'

import { isLifecycleQuery, isStickinessQuery } from '~/queries/utils'
import { InsightLogicProps, RetentionPeriod } from '~/types'

import { dateOptionToTimeIntervalMap } from './constants'
import type { retentionGraphLogicType } from './retentionGraphLogicType'
import { retentionLogic } from './retentionLogic'

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

export const retentionGraphLogic = kea<retentionGraphLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_RETENTION_LOGIC_KEY)),
    path((key) => ['scenes', 'retention', 'retentionGraphLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            ['querySource', 'dateRange', 'retentionFilter'],
            retentionLogic(props),
            ['results'],
        ],
    })),
    selectors({
        trendSeries: [
            (s) => [s.results, s.retentionFilter],
            (results, retentionFilter): RetentionTrendPayload[] => {
                const { period } = retentionFilter || {}

                return results.map((cohortRetention: ProcessedRetentionPayload, datasetIndex) => {
                    return {
                        id: datasetIndex,
                        days: cohortRetention.values.map((_, index) => `${period} ${index}`),
                        labels: cohortRetention.values.map((_, index) => `${period} ${index}`),
                        count: 0,
                        label: cohortRetention.date
                            ? period === 'Hour'
                                ? dayjs(cohortRetention.date).format('MMM D, h A')
                                : dayjs(cohortRetention.date).format('MMM D')
                            : cohortRetention.label,
                        data: cohortRetention.values.map((value) => value.percentage),
                        index: datasetIndex,
                    }
                })
            },
        ],

        incompletenessOffsetFromEnd: [
            (s) => [s.dateRange, s.retentionFilter, s.trendSeries],
            (dateRange, retentionFilter, trendSeries) => {
                const { date_to } = dateRange || {}
                const { period } = retentionFilter || {}

                // Returns negative number of points to paint over starting from end of array
                if (!trendSeries?.[0]?.days) {
                    return 0
                } else if (!date_to) {
                    return -1
                }
                const numUnits = trendSeries[0].days.length
                const interval = dateOptionToTimeIntervalMap?.[period ?? RetentionPeriod.Day]
                const startDate = dayjs().startOf(interval)
                const startIndex = trendSeries[0].days.findIndex(
                    (_, i) => dayjs(date_to).add(i - numUnits, interval as QUnitType) >= startDate
                )

                if (startIndex !== undefined && startIndex !== -1) {
                    return startIndex - trendSeries[0].days.length
                }
                return 0
            },
        ],

        aggregationGroupTypeIndex: [
            (s) => [s.querySource],
            (querySource) => {
                return (
                    (isLifecycleQuery(querySource) || isStickinessQuery(querySource)
                        ? null
                        : querySource?.aggregation_group_type_index) ?? 'people'
                )
            },
        ],
    }),
])
