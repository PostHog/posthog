import { connect, kea, key, path, props, selectors } from 'kea'
import { dayjs, QUnitType } from 'lib/dayjs'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { ProcessedRetentionPayload, RetentionTrendPayload } from 'scenes/retention/types'
import { teamLogic } from 'scenes/teamLogic'

import { DateRange } from '~/queries/schema/schema-general'
import { isLifecycleQuery, isStickinessQuery } from '~/queries/utils'
import { InsightLogicProps, RetentionPeriod } from '~/types'

import { dateOptionToTimeIntervalMap } from './constants'
import type { retentionGraphLogicType } from './retentionGraphLogicType'
import { MeanRetentionValue, retentionLogic } from './retentionLogic'

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
            ['hasValidBreakdown', 'results', 'selectedBreakdownValue', 'retentionMeans'],
            teamLogic,
            ['timezone'],
        ],
    })),
    selectors({
        trendSeries: [
            (s) => [s.results, s.retentionFilter],
            (results, retentionFilter): RetentionTrendPayload[] => {
                const { period } = retentionFilter || {}

                return results.map((cohortRetention: ProcessedRetentionPayload, datasetIndex) => {
                    return {
                        ...cohortRetention,
                        id: datasetIndex,
                        days: cohortRetention.values.map((_, index) => `${period} ${index}`),
                        labels: cohortRetention.values.map((_, index) => `${period} ${index}`),
                        count: 0,
                        label: cohortRetention.date
                            ? period === 'Hour'
                                ? cohortRetention.date.format('MMM D, h A')
                                : cohortRetention.date.format('MMM D')
                            : cohortRetention.label,
                        data: cohortRetention.values.map((value) => value.percentage),
                        index: datasetIndex,
                    }
                })
            },
        ],

        incompletenessOffsetFromEnd: [
            (s) => [s.dateRange, s.retentionFilter, s.trendSeries, s.timezone],
            (dateRange: DateRange | null | undefined, retentionFilter, trendSeries, timezone) => {
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
                const startDate = dayjs().tz(timezone).startOf(interval)
                const startIndex = trendSeries[0].days.findIndex(
                    (_, i) =>
                        dayjs(date_to)
                            .tz(timezone)
                            .add(i - numUnits, interval as QUnitType) >= startDate
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

        shouldShowMeanPerBreakdown: [
            (s) => [s.hasValidBreakdown, s.selectedBreakdownValue],
            (hasValidBreakdown: boolean, selectedBreakdownValue: string | number | boolean | null): boolean => {
                return hasValidBreakdown && selectedBreakdownValue === null
            },
        ],

        filteredTrendSeries: [
            (s) => [
                s.hasValidBreakdown,
                s.trendSeries,
                s.selectedBreakdownValue,
                s.retentionMeans,
                s.retentionFilter,
                s.shouldShowMeanPerBreakdown,
            ],
            (
                hasValidBreakdown: boolean,
                trendSeries: RetentionTrendPayload[],
                selectedBreakdownValue: string | number | boolean | null,
                retentionMeans: Record<string, MeanRetentionValue>,
                retentionFilter: any,
                shouldShowMeanPerBreakdown: boolean
            ): RetentionTrendPayload[] => {
                if (shouldShowMeanPerBreakdown) {
                    // Generate series from the mean retention data for each breakdown
                    if (!retentionMeans || Object.keys(retentionMeans).length === 0) {
                        return []
                    }

                    const { period } = retentionFilter || {}
                    const meanSeries: RetentionTrendPayload[] = []
                    let seriesId = 0

                    for (const breakdownKey in retentionMeans) {
                        const meanData = retentionMeans[breakdownKey]
                        // Skip overall mean in this view as we only want the means per breakdown
                        if (meanData.isOverall) {
                            continue
                        }

                        const numIntervals = meanData.meanPercentages.length
                        const days = Array.from({ length: numIntervals }, (_, i) => `${period} ${i}`)

                        meanSeries.push({
                            breakdown_value: meanData.label,
                            data: meanData.meanPercentages,
                            days: days,
                            labels: days,
                            count: meanData.totalCohortSize,
                            index: seriesId++,
                        })
                    }
                    return meanSeries
                }

                // Original logic for non-average view
                if (selectedBreakdownValue === null) {
                    // No specific breakdown selected:
                    // - If it's a valid breakdown query but no selection, return empty array (handled by the component)
                    // - If not a breakdown query at all, show all retention series
                    return hasValidBreakdown ? [] : trendSeries
                }
                // Return series with matching breakdown value
                return trendSeries.filter((series) => series.breakdown_value === selectedBreakdownValue)
            },
        ],
    }),
])
