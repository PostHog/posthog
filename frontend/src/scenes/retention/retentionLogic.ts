import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { dayjs } from 'lib/dayjs'
import { formatDateRange } from 'lib/utils'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { BREAKDOWN_OTHER_DISPLAY, BREAKDOWN_OTHER_STRING_LABEL } from 'scenes/insights/utils'
import { ProcessedRetentionPayload } from 'scenes/retention/types'
import { teamLogic } from 'scenes/teamLogic'

import { RetentionFilter, RetentionResult } from '~/queries/schema/schema-general'
import { isRetentionQuery, isValidBreakdown } from '~/queries/utils'
import { DateMappingOption, InsightLogicProps, RetentionPeriod } from '~/types'

import type { retentionLogicType } from './retentionLogicType'

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

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
        ],
        actions: [insightVizDataLogic(props), ['updateInsightFilter', 'updateDateRange']],
    })),
    actions({
        setSelectedBreakdownValue: (value: string | number | boolean | null) => ({ value }),
    }),
    reducers({
        selectedBreakdownValue: [
            null as string | number | boolean | null,
            {
                setSelectedBreakdownValue: (_, { value }) => value,
            },
        ],
    }),
    selectors({
        hasValidBreakdown: [(s) => [s.breakdownFilter], (breakdownFilter) => isValidBreakdown(breakdownFilter)],
        results: [
            (s) => [s.insightQuery, s.insightData, s.retentionFilter, s.timezone],
            (insightQuery, insightData, retentionFilter, timezone): ProcessedRetentionPayload[] => {
                const rawResults = isRetentionQuery(insightQuery) ? insightData?.result ?? [] : []

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
    }),
])
