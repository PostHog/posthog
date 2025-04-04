import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
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
            ['dateRange', 'retentionFilter', 'vizSpecificOptions', 'theme'],
            retentionLogic(props),
            ['results', 'selectedBreakdownValue'],
        ],
        actions: [retentionLogic(props), ['setSelectedBreakdownValue']],
    })),

    actions({
        toggleBreakdown: (breakdownValue: string) => ({ breakdownValue }),
        setExpandedBreakdowns: (expandedBreakdowns: Record<string, boolean>) => ({ expandedBreakdowns }),
    }),

    reducers({
        expandedBreakdowns: [
            {} as Record<string, boolean>,
            {
                toggleBreakdown: (state, { breakdownValue }) => ({
                    ...state,
                    [breakdownValue]: !state[breakdownValue],
                }),
                setExpandedBreakdowns: (_, { expandedBreakdowns }) => expandedBreakdowns,
            },
        ],
    }),

    afterMount(({ actions, values }) => {
        autoExpandSingleBreakdown(values.tableRowsSplitByBreakdownValue, actions.setExpandedBreakdowns)
    }),

    listeners(({ actions, values }) => ({
        setSelectedBreakdownValue: () => {
            autoExpandSingleBreakdown(values.tableRowsSplitByBreakdownValue, actions.setExpandedBreakdowns)
        },
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
    }),
])

// Helper function to auto-expand a single breakdown
function autoExpandSingleBreakdown(
    tableRowsSplitByBreakdownValue: Record<string, RetentionTableRow[]>,
    setExpandedBreakdownsAction: (expandedBreakdowns: Record<string, boolean>) => void
): void {
    const breakdownKeys = Object.keys(tableRowsSplitByBreakdownValue)
    if (breakdownKeys.length === 1) {
        const singleBreakdownValue = breakdownKeys[0]
        setExpandedBreakdownsAction({ [singleBreakdownValue]: true })
    }
}
