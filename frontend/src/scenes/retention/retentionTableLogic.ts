import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { capitalizeFirstLetter } from 'lib/utils'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { InsightQueryNode } from '~/queries/schema/schema-general'
import { isRetentionQuery } from '~/queries/utils'
import { InsightLogicProps, InsightType } from '~/types'

import { dateOptionPlurals } from './constants'
import { retentionLogic } from './retentionLogic'
import type { retentionTableLogicType } from './retentionTableLogicType'
import { NO_BREAKDOWN_VALUE, ProcessedRetentionPayload, RetentionTableRow } from './types'
import { formatRetentionCohortLabel } from './utils'

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

export const retentionTableLogic = kea<retentionTableLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_RETENTION_LOGIC_KEY)),
    path((key) => ['scenes', 'retention', 'retentionTableLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            ['dateRange', 'retentionFilter', 'vizSpecificOptions', 'theme', 'insightQuery'],
            retentionLogic(props),
            ['results', 'filteredResults', 'selectedBreakdownValue', 'retentionMeans', 'breakdownDisplayNames'],
        ],
        actions: [retentionLogic(props), ['setSelectedBreakdownValue']],
    })),

    actions({
        toggleBreakdown: (breakdownValue: string) => ({ breakdownValue }),
        setExpandedBreakdowns: (expandedBreakdowns: Record<string, boolean>) => ({ expandedBreakdowns }),
        setHoveredColumn: (columnIndex: number | null) => ({ columnIndex }),
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
        hoveredColumn: [
            null as number | null,
            {
                setHoveredColumn: (_, { columnIndex }) => columnIndex,
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

        tableRows: [
            (s) => [s.filteredResults, s.retentionFilter],
            (filteredResults, retentionFilter): RetentionTableRow[] => {
                const { period } = retentionFilter || {}

                return filteredResults.map((currentResult: ProcessedRetentionPayload) => {
                    const cohortSize = currentResult.values?.[0] ? currentResult.values[0].count : 0

                    return {
                        label: formatRetentionCohortLabel(currentResult, period),
                        cohortSize,
                        values: currentResult.values,
                        breakdown_value: currentResult.breakdown_value,
                    }
                })
            },
        ],

        tableHeaders: [
            (s) => [s.results, s.insightQuery],
            (results: ProcessedRetentionPayload[], insightQuery: InsightQueryNode | null): string[] => {
                if (results.length > 0 && results[0].values.length > 0) {
                    if (isRetentionQuery(insightQuery) && insightQuery.retentionFilter?.retentionCustomBrackets) {
                        const { period, retentionCustomBrackets } = insightQuery.retentionFilter
                        const unit = capitalizeFirstLetter(dateOptionPlurals[period || 'Day'])
                        const labels = [`${period || 'Day'} 0`]
                        let cumulativeTotal = 1
                        for (const bracketSize of retentionCustomBrackets) {
                            const start = cumulativeTotal
                            const end = cumulativeTotal + bracketSize - 1
                            if (start === end) {
                                labels.push(`${unit} ${start}`)
                            } else {
                                labels.push(`${unit} ${start}-${end}`)
                            }
                            cumulativeTotal += bracketSize
                        }
                        return labels
                    }
                    if (isRetentionQuery(insightQuery)) {
                        return results[0].values.map((_, i) => `${insightQuery.retentionFilter?.period || 'Day'} ${i}`)
                    }
                }
                return []
            },
        ],
        tableRowsSplitByBreakdownValue: [
            (s) => [s.tableRows],
            (tableRows) => {
                return tableRows.reduce(
                    (acc, row) => {
                        const breakdownValue = row.breakdown_value ?? NO_BREAKDOWN_VALUE
                        acc[breakdownValue] = [...(acc[breakdownValue] || []), row]
                        return acc
                    },
                    {} as Record<string, RetentionTableRow[]>
                )
            },
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
