import { connect, kea, key, path, props, selectors } from 'kea'
import { dayjs } from 'lib/dayjs'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { InsightLogicProps, InsightType } from '~/types'

import { retentionLogic } from './retentionLogic'
import type { retentionTableLogicType } from './retentionTableLogicType'
import { NO_BREAKDOWN_VALUE, ProcessedRetentionPayload, RetentionTableRow } from './types'

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

export const retentionTableLogic = kea<retentionTableLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_RETENTION_LOGIC_KEY)),
    path((key) => ['scenes', 'retention', 'retentionTableLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            ['dateRange', 'retentionFilter', 'breakdownFilter', 'vizSpecificOptions', 'theme'],
            retentionLogic(props),
            ['results', 'selectedBreakdownValue'],
        ],
    })),
    selectors({
        retentionVizOptions: [
            (s) => [s.vizSpecificOptions],
            (vizSpecificOptions) => vizSpecificOptions?.[InsightType.RETENTION],
        ],
        hideSizeColumn: [(s) => [s.retentionVizOptions], (retentionVizOptions) => retentionVizOptions?.hideSizeColumn],

        filteredResults: [
            (s) => [s.results, s.selectedBreakdownValue],
            (results, selectedBreakdownValue) => {
                if (!results || results.length === 0) {
                    return []
                }
                if (selectedBreakdownValue === null) {
                    return results
                }

                // Return only results for the selected breakdown
                return results.filter((result) => result.breakdown_value === selectedBreakdownValue)
            },
        ],

        tableRows: [
            (s) => [s.filteredResults, s.retentionFilter, s.hideSizeColumn],
            (filteredResults, retentionFilter): RetentionTableRow[] => {
                const { period } = retentionFilter || {}

                return filteredResults.map((currentResult: ProcessedRetentionPayload) => {
                    const currentDate = dayjs.utc(currentResult.date)

                    let label // Prepare for some date gymnastics

                    switch (period) {
                        case 'Hour':
                            label = currentDate.format('MMM D, h A')
                            break
                        case 'Month':
                            label = currentDate.format('MMM YYYY')
                            break
                        case 'Week': {
                            const startDate = currentDate
                            const endDate = startDate.add(6, 'day') // To show last day of the week we add 6 days, not 7
                            label = `${startDate.format('MMM D')} to ${endDate.format('MMM D')}`
                            break
                        }
                        default:
                            label = currentDate.format('MMM D')
                    }

                    const cohortSize = currentResult.values?.[0] ? currentResult.values[0].count : 0

                    return {
                        label,
                        cohortSize,
                        values: currentResult.values,
                        breakdown_value: currentResult.breakdown_value,
                    }
                })
            },
        ],

        tableRowsSplitByBreakdownValue: [
            (s) => [s.tableRows],
            (tableRows): Record<string, RetentionTableRow[]> =>
                tableRows.reduce((acc, row) => {
                    acc[row.breakdown_value ?? NO_BREAKDOWN_VALUE] = [
                        ...(acc[row.breakdown_value ?? NO_BREAKDOWN_VALUE] || []),
                        row,
                    ]
                    return acc
                }, {} as Record<string, RetentionTableRow[]>),
        ],

        breakdownValues: [
            (s) => [s.results],
            (results) => {
                if (!results || results.length === 0) {
                    return []
                }
                // Extract unique breakdown values from results
                const valueSet = new Set(
                    results.filter((result) => 'breakdown_value' in result).map((result) => result.breakdown_value)
                )
                return Array.from(valueSet)
            },
        ],
    }),
])
