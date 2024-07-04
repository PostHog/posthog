import type { LemonSegmentedButtonOption } from '@posthog/lemon-ui'
import { actions, kea, listeners, path, reducers } from 'kea'
import { UniversalFiltersGroup } from 'lib/components/UniversalFilters/UniversalFilters'

import { DateRange, ErrorTrackingOrder } from '~/queries/schema'
import { FilterLogicalOperator } from '~/types'

import type { errorTrackingLogicType } from './errorTrackingLogicType'

const lastHour = { value: '1h', label: '1h' }
const lastDay = { value: '24h', label: '24h' }
const lastMonth = { value: 'mStart', label: 'Month' }
const lastYear = { value: 'yStart', label: 'Year' }

export type SparklineOption = LemonSegmentedButtonOption<string>

export const errorTrackingLogic = kea<errorTrackingLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingLogic']),

    actions({
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setOrder: (order: ErrorTrackingOrder) => ({ order }),
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
        order: [
            'last_seen' as ErrorTrackingOrder,
            { persist: true },
            {
                setOrder: (_, { order }) => order,
            },
        ],
        filterGroup: [
            { type: FilterLogicalOperator.And, values: [] } as UniversalFiltersGroup,
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
            const options: SparklineOption[] = []

            if (date_from === 'dStart' || date_from === '-24h') {
                // today and last 24 hours
                options.push(lastDay, lastHour)
            } else if (date_from === '-1dStart') {
                // yesterday
                options.push({ value: '-1d24h', label: '24h' }, { value: '-1d1h', label: '1h' })
            } else if (date_from === 'mStart') {
                // this month
                options.push(lastMonth, lastDay)
            } else if (date_from === 'yStart') {
                // this year
                options.push(lastYear, lastMonth)
            } else if (date_from === 'all') {
                // all time
                options.push(lastYear, lastMonth, lastDay)
            } else if (date_from) {
                const isRelative = date_from.match(/-\d+[hdmy]/)
                if (isRelative) {
                    const value = date_from?.replace('-', '')
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
        },
    })),
])
