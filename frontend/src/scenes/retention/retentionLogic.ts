import { mean, sum } from 'd3'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { dayjs } from 'lib/dayjs'
import { formatDateRange } from 'lib/utils'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { BREAKDOWN_OTHER_DISPLAY, BREAKDOWN_OTHER_STRING_LABEL, formatBreakdownLabel } from 'scenes/insights/utils'
import { ProcessedRetentionPayload } from 'scenes/retention/types'
import { teamLogic } from 'scenes/teamLogic'

import { cohortsModel } from '~/models/cohortsModel'
import { RetentionFilter, RetentionResult } from '~/queries/schema/schema-general'
import { isRetentionQuery, isValidBreakdown } from '~/queries/utils'
import { BreakdownKeyType, CohortType, DateMappingOption, InsightLogicProps, RetentionPeriod } from '~/types'

import type { retentionLogicType } from './retentionLogicType'

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'
export const OVERALL_MEAN_KEY = '__overall__'
export const DEFAULT_RETENTION_TOTAL_INTERVALS = 8
export const RETENTION_EMPTY_BREAKDOWN_VALUE = '(empty)'
export const MAX_BRACKETS = 30

// Define a type for the output of the retentionMeans selector
export interface MeanRetentionValue {
    label: string | number | null
    meanPercentages: number[]
    totalCohortSize: number
    isOverall?: boolean
}

export const retentionLogic = kea<retentionLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_RETENTION_LOGIC_KEY)),
    path((key) => ['scenes', 'retention', 'retentionLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            ['breakdownFilter', 'dateRange', 'insightQuery', 'insightData', 'querySource', 'retentionFilter'],
            teamLogic,
            ['timezone'],
            cohortsModel,
            ['cohortsById'],
        ],
        actions: [insightVizDataLogic(props), ['updateInsightFilter', 'updateDateRange', 'updateBreakdownFilter']],
    })),
    actions({
        setSelectedBreakdownValue: (value: string | number | boolean | null) => ({ value }),
        setLocalCustomBrackets: (brackets: (string | number)[]) => ({ brackets }),
        updateLocalCustomBracket: (index: number, value: number | undefined) => ({ index, value }),
        addCustomBracket: () => ({}),
        removeCustomBracket: (index: number) => ({ index }),
    }),
    listeners(({ actions, values }) => ({
        updateBreakdownFilter: () => {
            // Reset selected breakdown value when breakdown filter changes
            // This prevents the dropdown from showing invalid cohort IDs
            actions.setSelectedBreakdownValue(null)
        },
        updateLocalCustomBracket: async (_, breakpoint) => {
            await breakpoint(1000)
            const { localCustomBrackets, retentionFilter } = values
            const numericBrackets = localCustomBrackets
                .map((b) => (typeof b === 'string' ? parseInt(b, 10) : b))
                .filter((b): b is number => !isNaN(Number(b)) && Number(b) > 0)

            if (JSON.stringify(numericBrackets) !== JSON.stringify(retentionFilter?.retentionCustomBrackets || [])) {
                actions.updateInsightFilter({
                    retentionCustomBrackets: numericBrackets.length > 0 ? numericBrackets : undefined,
                })
            }
        },
        updateInsightFilter: ({ insightFilter }) => {
            const retentionFilter = insightFilter as RetentionFilter
            if (retentionFilter.retentionCustomBrackets !== undefined) {
                const { localCustomBrackets } = values
                const numericLocal = localCustomBrackets
                    .map((b) => (typeof b === 'string' ? parseInt(b, 10) : b))
                    .filter((b): b is number => !isNaN(Number(b)) && Number(b) > 0)

                const incomingBrackets = retentionFilter.retentionCustomBrackets || []

                if (JSON.stringify(numericLocal) !== JSON.stringify(incomingBrackets)) {
                    actions.setLocalCustomBrackets([...incomingBrackets])
                }
            }
        },
        removeCustomBracket: async (_, breakpoint) => {
            await breakpoint(1000)
            const { localCustomBrackets, retentionFilter } = values
            const numericBrackets = localCustomBrackets
                .map((b) => (typeof b === 'string' ? parseInt(b, 10) : b))
                .filter((b): b is number => !isNaN(Number(b)) && Number(b) > 0)

            // Only update if we still have at least one bracket (even if empty) to keep custom brackets enabled
            if (
                localCustomBrackets.length > 0 &&
                JSON.stringify(numericBrackets) !== JSON.stringify(retentionFilter?.retentionCustomBrackets || [])
            ) {
                actions.updateInsightFilter({
                    retentionCustomBrackets: numericBrackets.length > 0 ? numericBrackets : [],
                })
            }
        },
    })),
    reducers({
        selectedBreakdownValue: [
            null as string | number | boolean | null,
            {
                setSelectedBreakdownValue: (_, { value }) => value,
            },
        ],
        localCustomBrackets: [
            [] as (string | number)[],
            {
                setLocalCustomBrackets: (_, { brackets }) => brackets,
                updateLocalCustomBracket: (state, { index, value }) => {
                    const newBrackets = [...state]
                    newBrackets[index] = value ?? ''
                    return newBrackets
                },
                addCustomBracket: (state) => {
                    if (state.length >= MAX_BRACKETS) {
                        return state
                    }
                    return [...state, '']
                },
                removeCustomBracket: (state, { index }) => {
                    const newBrackets = [...state]
                    newBrackets.splice(index, 1)
                    if (newBrackets.filter((b) => b !== '').length === 0) {
                        return ['']
                    }
                    return newBrackets
                },
            },
        ],
    }),
    selectors({
        hasValidBreakdown: [(s) => [s.breakdownFilter], (breakdownFilter) => isValidBreakdown(breakdownFilter)],
        results: [
            (s) => [s.insightQuery, s.insightData, s.retentionFilter, s.timezone],
            (insightQuery, insightData, retentionFilter, timezone): ProcessedRetentionPayload[] => {
                const rawResults = isRetentionQuery(insightQuery) ? (insightData?.result ?? []) : []

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
                        const cellDate = dayjs(result.date).tz(timezone).add(index, periodUnit)
                        const now = dayjs().tz(timezone)

                        return {
                            ...value,
                            percentage,
                            cellDate,
                            isCurrentPeriod: cellDate.isSame(now, periodUnit),
                            isFuture: cellDate.isAfter(now),
                        }
                    }),
                }))

                // Filter out future values and handle breakdown label
                return results.map((result) => ({
                    ...result,
                    date: dayjs(result.date).tz(timezone),
                    // Replace internal "other" breakdown value with display value
                    breakdown_value:
                        result.breakdown_value === BREAKDOWN_OTHER_STRING_LABEL
                            ? BREAKDOWN_OTHER_DISPLAY
                            : result.breakdown_value,
                    values: result.values.filter((value) => !value.isFuture),
                }))
            },
        ],

        retentionMeans: [
            (s) => [s.results, s.retentionFilter, s.hasValidBreakdown],
            (
                results: ProcessedRetentionPayload[],
                retentionFilter: RetentionFilter | undefined,
                hasValidBreakdown: boolean
            ): Record<string, MeanRetentionValue> => {
                if (!results.length || !retentionFilter) {
                    return {}
                }

                const { meanRetentionCalculation } = retentionFilter
                const numIntervals = results.length > 0 ? results[0].values.length : 0

                const groupedByBreakdown: Record<string, ProcessedRetentionPayload[]> = {}

                if (hasValidBreakdown) {
                    results.forEach((result) => {
                        const key = result.breakdown_value ?? RETENTION_EMPTY_BREAKDOWN_VALUE
                        if (!groupedByBreakdown[key]) {
                            groupedByBreakdown[key] = []
                        }
                        groupedByBreakdown[key].push(result)
                    })
                } else {
                    // No valid breakdown, so group all results under the overall key
                    groupedByBreakdown[OVERALL_MEAN_KEY] = [...results]
                }

                const means: Record<string, MeanRetentionValue> = {}

                for (const breakdownKey in groupedByBreakdown) {
                    const breakdownRows = groupedByBreakdown[breakdownKey]
                    if (breakdownRows.length === 0) {
                        continue
                    }

                    const meanPercentagesForBreakdown: number[] = []
                    const isOverallGroupWithoutBreakdown = breakdownKey === OVERALL_MEAN_KEY && !hasValidBreakdown
                    const label = isOverallGroupWithoutBreakdown
                        ? 'Overall'
                        : (breakdownRows[0]?.breakdown_value ?? null)

                    for (let intervalIndex = 0; intervalIndex < numIntervals; intervalIndex++) {
                        const validRows = breakdownRows.filter(
                            (row) =>
                                row.values[intervalIndex] && // Ensure data for this interval exists
                                !row.values[intervalIndex].isCurrentPeriod && // don't include incomplete periods
                                row.values[0]?.count > 0 // only include rows which had non zero cohort size (so that they don't pull the mean down)
                        )

                        let currentIntervalMean = 0
                        if (validRows.length > 0) {
                            if (meanRetentionCalculation === 'weighted') {
                                const weightedValueSum = sum(
                                    validRows,
                                    (row) => (row.values[intervalIndex]?.percentage || 0) * (row.values[0]?.count || 0)
                                )
                                const totalWeight = sum(validRows, (row) => row.values[0]?.count || 0)
                                currentIntervalMean = totalWeight > 0 ? weightedValueSum / totalWeight : 0
                            } else {
                                // Simple mean
                                currentIntervalMean =
                                    mean(validRows.map((row) => row.values[intervalIndex]?.percentage || 0)) || 0
                            }
                        }
                        meanPercentagesForBreakdown.push(currentIntervalMean)
                    }

                    const totalCohortSizeForGroup = sum(breakdownRows.map((row) => row.values[0]?.count || 0))

                    means[breakdownKey] = {
                        label: label,
                        meanPercentages: meanPercentagesForBreakdown,
                        totalCohortSize: totalCohortSizeForGroup,
                        isOverall: isOverallGroupWithoutBreakdown,
                    }
                }
                return means
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

        breakdownDisplayNames: [
            (s) => [s.breakdownValues, s.breakdownFilter, s.cohortsById],
            (
                breakdownValues: (string | number | boolean | null)[],
                breakdownFilter: any,
                cohortsById: Partial<Record<string | number, CohortType>>
            ): Record<string, string> => {
                return breakdownValues.reduce(
                    (acc, breakdownValue) => {
                        const key = String(breakdownValue ?? '')

                        if (breakdownValue === null || breakdownValue === '') {
                            acc[key] = '(empty)'
                        } else {
                            // Convert cohortsById to array for formatBreakdownLabel
                            const cohorts = Object.values(cohortsById).filter(Boolean) as CohortType[]
                            // Convert string breakdown value back to original type for formatBreakdownLabel
                            const originalBreakdownValue =
                                typeof breakdownValue === 'string' && /^\d+$/.test(breakdownValue)
                                    ? Number(breakdownValue)
                                    : breakdownValue
                            const formattedLabel = formatBreakdownLabel(
                                originalBreakdownValue as BreakdownKeyType,
                                breakdownFilter,
                                cohorts,
                                undefined
                            )
                            acc[key] = formattedLabel
                        }
                        return acc
                    },
                    {} as Record<string, string>
                )
            },
        ],
    }),
])
