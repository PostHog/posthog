import { dayjs } from 'lib/dayjs'
import { kea, props, key, path, connect, selectors } from 'kea'
import { range } from 'lib/utils'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { InsightLogicProps, InsightType } from '~/types'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { retentionLogic } from './retentionLogic'

import type { retentionTableLogicType } from './retentionTableLogicType'

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

const periodIsLatest = (date_to: string | null, period: string | null): boolean => {
    if (!date_to || !period) {
        return true
    }

    const curr = dayjs(date_to)
    if (
        (period == 'Hour' && curr.isSame(dayjs(), 'hour')) ||
        (period == 'Day' && curr.isSame(dayjs(), 'day')) ||
        (period == 'Week' && curr.isSame(dayjs(), 'week')) ||
        (period == 'Month' && curr.isSame(dayjs(), 'month'))
    ) {
        return true
    } else {
        return false
    }
}

export const retentionTableLogic = kea<retentionTableLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_RETENTION_LOGIC_KEY)),
    path((key) => ['scenes', 'retention', 'retentionTableLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            ['dateRange', 'retentionFilter', 'breakdown', 'vizSpecificOptions'],
            retentionLogic(props),
            ['results'],
        ],
    })),
    selectors({
        isLatestPeriod: [
            (s) => [s.dateRange, s.retentionFilter],
            (dateRange, retentionFilter) => periodIsLatest(dateRange?.date_to || null, retentionFilter?.period || null),
        ],

        retentionVizOptions: [
            (s) => [s.vizSpecificOptions],
            (vizSpecificOptions) => vizSpecificOptions?.[InsightType.RETENTION],
        ],
        hideSizeColumn: [(s) => [s.retentionVizOptions], (retentionVizOptions) => retentionVizOptions?.hideSizeColumn],

        maxIntervalsCount: [
            (s) => [s.results],
            (results) => {
                return Math.max(...results.map((result) => result.values.length))
            },
        ],

        tableHeaders: [
            (s) => [s.results, s.hideSizeColumn],
            (results, hideSizeColumn) => {
                return ['Cohort', ...(hideSizeColumn ? [] : ['Size']), ...results.map((x) => x.label)]
            },
        ],

        tableRows: [
            (s) => [s.results, s.maxIntervalsCount, s.retentionFilter, s.breakdown, s.hideSizeColumn],
            (results, maxIntervalsCount, retentionFilter, breakdown, hideSizeColumn) => {
                const { period } = retentionFilter || {}
                const { breakdowns } = breakdown || {}

                return range(maxIntervalsCount).map((rowIndex: number) => [
                    // First column is the cohort label
                    breakdowns?.length
                        ? results[rowIndex].label
                        : period === 'Hour'
                        ? dayjs(results[rowIndex].date).format('MMM D, h A')
                        : dayjs(results[rowIndex].date).format('MMM D'),
                    // Second column is the first value (which is essentially the total)
                    ...(hideSizeColumn ? [] : [results[rowIndex].values[0].count]),
                    // All other columns are rendered as percentage
                    ...results[rowIndex].values.map((row) => {
                        const percentage =
                            results[rowIndex].values[0]['count'] > 0
                                ? (row['count'] / results[rowIndex].values[0]['count']) * 100
                                : 0

                        return {
                            count: row['count'],
                            percentage,
                        }
                    }),
                ])
            },
        ],
    }),
])
