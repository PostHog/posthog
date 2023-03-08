import { dayjs } from 'lib/dayjs'
import { kea } from 'kea'
import { range } from 'lib/utils'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { InsightLogicProps } from '~/types'

import { abstractRetentionLogic } from './abstractRetentionLogic'

import type { retentionTableLogicType } from './retentionTableLogicType'

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

export const retentionTableLogic = kea<retentionTableLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps(DEFAULT_RETENTION_LOGIC_KEY),
    path: (key) => ['scenes', 'retention', 'retentionTableLogic', key],
    connect: (props: InsightLogicProps) => ({
        values: [abstractRetentionLogic(props), ['retentionFilter', 'breakdown', 'results']],
    }),
    selectors: {
        maxIntervalsCount: [
            (s) => [s.results],
            (results) => {
                return Math.max(...results.map((result) => result.values.length))
            },
        ],

        tableHeaders: [
            (s) => [s.results],
            (results) => {
                return ['Cohort', 'Size', ...results.map((x) => x.label)]
            },
        ],

        tableRows: [
            (s) => [s.results, s.maxIntervalsCount, s.retentionFilter, s.breakdown],
            (results, maxIntervalsCount, { period }, { breakdowns }) => {
                return range(maxIntervalsCount).map((rowIndex: number) => [
                    // First column is the cohort label
                    breakdowns?.length
                        ? results[rowIndex].label
                        : period === 'Hour'
                        ? dayjs(results[rowIndex].date).format('MMM D, h A')
                        : dayjs.utc(results[rowIndex].date).format('MMM D'),
                    // Second column is the first value (which is essentially the total)
                    results[rowIndex].values[0].count,
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
    },
})
