import { connect, kea, key, path, props, selectors } from 'kea'
import { dayjs, QUnitType } from 'lib/dayjs'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { RetentionTrendPayload } from 'scenes/retention/types'

import { isLifecycleQuery, isStickinessQuery } from '~/queries/utils'
import { InsightLogicProps, RetentionPeriod } from '~/types'

import { dateOptionToTimeIntervalMap } from './constants'
import type { retentionLineGraphLogicType } from './retentionLineGraphLogicType'
import { retentionLogic } from './retentionLogic'

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

export const retentionLineGraphLogic = kea<retentionLineGraphLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_RETENTION_LOGIC_KEY)),
    path((key) => ['scenes', 'retention', 'retentionLineGraphLogic', key]),
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
                const { period, retentionReference, cumulative } = retentionFilter || {}
                // If the retention reference option is specified as previous,
                // then translate retention rates to relative to previous,
                // otherwise, just use what the result was originally.
                //
                // Our input results might looks something like
                //
                //   Cohort 1 | 1000 | 120 | 190 | 170 | 140
                //   Cohort 2 | 6003 | 300 | 100 | 120 | 50
                //
                // If `retentionFilter.retentionReference` is not "previous"
                // we want to calculate the percentages of the sizes compared
                // to the first value. If we have "previous" we want to go
                // further and translate these numbers into percentage of the
                // previous value so we get some idea for the rate of
                // convergence.

                return results.map((cohortRetention, datasetIndex) => {
                    let retentionPercentages = cohortRetention.values
                        .map((value) => value.count / cohortRetention.values[0].count)
                        .map((value) => (isNaN(value) ? 0 : 100 * value))

                    if (cumulative) {
                        retentionPercentages = retentionPercentages.map((value, valueIndex, arr) => {
                            let cumulativeValue = value
                            for (let i = valueIndex + 1; i < arr.length; i++) {
                                cumulativeValue += arr[i]
                            }
                            return Math.min(cumulativeValue, 100)
                        })
                    }

                    // To calculate relative percentages, we take for instance Cohort 1 as percentages
                    // of the cohort size and create another series that has a 100 at prepended so we have
                    //
                    //   Cohort 1'  | 100  | 12  | 19 | 17 | 14
                    //   Cohort 1'' | 100  | 100 | 12 | 19 | 17 | 14
                    //
                    // And from here construct a third, relative percentage series by dividing the
                    // top numbers by the bottom numbers to get
                    //
                    //   Cohort 1''' | 1 | 0.12 | ...
                    const paddedValues = [100].concat(retentionPercentages)

                    return {
                        id: datasetIndex,
                        days: retentionPercentages.map((_, index) => `${period} ${index}`),
                        labels: retentionPercentages.map((_, index) => `${period} ${index}`),
                        count: 0,
                        label: cohortRetention.date
                            ? period === 'Hour'
                                ? dayjs(cohortRetention.date).format('MMM D, h A')
                                : dayjs(cohortRetention.date).format('MMM D')
                            : cohortRetention.label,
                        data:
                            retentionReference === 'previous'
                                ? retentionPercentages
                                      // Zip together the current a previous values, filling
                                      // in with 100 for the first index
                                      .map((value, index) => [value, paddedValues[index]])
                                      // map values to percentage of previous
                                      .map(([value, previous]) => (100 * value) / previous)
                                : retentionPercentages,
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
