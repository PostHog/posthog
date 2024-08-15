import { connect, kea, key, path, props, selectors } from 'kea'
import { dayjs } from 'lib/dayjs'
import { range } from 'lib/utils'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { InsightLogicProps, InsightType } from '~/types'

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
    }
    return false
}

export const retentionTableLogic = kea<retentionTableLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_RETENTION_LOGIC_KEY)),
    path((key) => ['scenes', 'retention', 'retentionTableLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            ['dateRange', 'retentionFilter', 'breakdownFilter', 'vizSpecificOptions'],
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
            (s) => [s.results, s.maxIntervalsCount, s.retentionFilter, s.breakdownFilter, s.hideSizeColumn],
            (results, maxIntervalsCount, retentionFilter, breakdownFilter, hideSizeColumn) => {
                const { period, cumulative } = retentionFilter || {}
                const { breakdowns } = breakdownFilter || {}

                return range(maxIntervalsCount).map((index: number) => {
                    const currentResult = results[index]
                    let firstColumn // Prepare for some date gymnastics

                    if (breakdowns?.length) {
                        firstColumn = currentResult.label
                    } else {
                        switch (period) {
                            case 'Hour':
                                firstColumn = dayjs.utc(currentResult.date).format('MMM D, h A')
                                break
                            case 'Month':
                                firstColumn = dayjs.utc(currentResult.date).format('MMM YYYY')
                                break
                            case 'Week': {
                                const startDate = dayjs.utc(currentResult.date)
                                const endDate = startDate.add(6, 'day') // To show last day of the week we add 6 days, not 7
                                firstColumn = `${startDate.format('MMM D')} to ${endDate.format('MMM D')}`
                                break
                            }
                            default:
                                firstColumn = dayjs.utc(currentResult.date).format('MMM D')
                        }
                    }

                    const secondColumn = hideSizeColumn ? [] : [currentResult.values[0].count]

                    const otherColumns = currentResult.values.map((value, valueIndex) => {
                        const totalCount = currentResult.values[0]['count']
                        let count = value['count']

                        if (cumulative && valueIndex > 0) {
                            for (let i = valueIndex + 1; i < currentResult.values.length; i++) {
                                count += currentResult.values[i]['count']
                            }
                            count = Math.min(count, totalCount)
                        }

                        const percentage = totalCount > 0 ? (count / totalCount) * 100 : 0

                        return {
                            count,
                            percentage,
                        }
                    })

                    return [firstColumn, ...secondColumn, ...otherColumns]
                })
            },
        ],
    }),
])
