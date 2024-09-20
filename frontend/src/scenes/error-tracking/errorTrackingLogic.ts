import type { LemonSegmentedButtonOption } from '@posthog/lemon-ui'
import { actions, kea, listeners, path, reducers } from 'kea'
import { UniversalFiltersGroup } from 'lib/components/UniversalFilters/UniversalFilters'

import { DateRange } from '~/queries/schema'
import { FilterLogicalOperator } from '~/types'

import type { errorTrackingLogicType } from './errorTrackingLogicType'

const lastHour = { value: '1h', label: '1h' }
const lastDay = { value: '24h', label: '24h' }
const lastMonth = { value: 'mStart', label: 'Month' }
const lastYear = { value: 'yStart', label: 'Year' }

export type SparklineOption = LemonSegmentedButtonOption<string>

const customOptions: Record<string, SparklineOption[]> = {
    dStart: [lastDay, lastHour],
    '-24h': [lastDay, lastHour],
    '-1dStart': [
        { value: '-1d24h', label: '24h' },
        { value: '-1d1h', label: '1h' },
    ],
    mStart: [lastMonth, lastDay],
    yStart: [lastYear, lastMonth],
    all: [lastYear, lastMonth, lastDay],
}

const DEFAULT_FILTER_GROUP = {
    type: FilterLogicalOperator.And,
    values: [{ type: FilterLogicalOperator.And, values: [] }],
}

export const errorTrackingLogic = kea<errorTrackingLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingLogic']),

    actions({
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setAssignee: (assignee: number | null) => ({ assignee }),
        setFilterGroup: (filterGroup: UniversalFiltersGroup) => ({ filterGroup }),
        setFilterTestAccounts: (filterTestAccounts: boolean) => ({ filterTestAccounts }),
        setSparklineSelectedPeriod: (period: string | null) => ({ period }),
        _setSparklineOptions: (options: SparklineOption[]) => ({ options }),
    }),
    reducers({
        dateRange: [
            { date_from: '-7d', date_to: null } as DateRange,
            { persist: true },
            {
                setDateRange: (_, { dateRange }) => dateRange,
            },
        ],
        assignee: [
            null as number | null,
            { persist: true },
            {
                setAssignee: (_, { assignee }) => assignee,
            },
        ],
        filterGroup: [
            DEFAULT_FILTER_GROUP as UniversalFiltersGroup,
            { persist: true },
            {
                setFilterGroup: (_, { filterGroup }) => filterGroup,
            },
        ],
        filterTestAccounts: [
            false as boolean,
            { persist: true },
            {
                setFilterTestAccounts: (_, { filterTestAccounts }) => filterTestAccounts,
            },
        ],
        sparklineSelectedPeriod: [
            lastDay.value as string | null,
            { persist: true },
            {
                setSparklineSelectedPeriod: (_, { period }) => period,
            },
        ],
        sparklineOptions: [
            [lastDay, lastHour] as SparklineOption[],
            { persist: true },
            {
                _setSparklineOptions: (_, { options }) => options,
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        setDateRange: ({ dateRange: { date_from } }) => {
            if (date_from) {
                const options: SparklineOption[] = customOptions[date_from] ?? []

                if (options.length === 0) {
                    const isRelative = date_from.match(/-\d+[hdmy]/)

                    if (isRelative) {
                        const value = date_from?.replace('-', '')
                        // TODO does this add or replace?
                        options.push({ value: value, label: value }, lastDay)
                    }
                }

                if (options.length === 0) {
                    actions.setSparklineSelectedPeriod(null)
                } else {
                    const possibleValues = options.map((o) => o.value)

                    if (!values.sparklineSelectedPeriod || !possibleValues.includes(values.sparklineSelectedPeriod)) {
                        actions.setSparklineSelectedPeriod(options[0].value)
                    }
                }

                actions._setSparklineOptions(options)
            } else {
                actions.setSparklineSelectedPeriod(null)
                actions._setSparklineOptions([])
            }
        },
    })),
])
