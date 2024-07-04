import { LemonSegmentedButtonOption } from '@posthog/lemon-ui'
import { actions, kea, listeners, path, reducers } from 'kea'
import { UniversalFiltersGroup } from 'lib/components/UniversalFilters/UniversalFilters'

import { DateRange, ErrorTrackingOrder } from '~/queries/schema'
import { FilterLogicalOperator } from '~/types'

import type { errorTrackingLogicType } from './errorTrackingLogicType'

const oneHour = { value: '1h', label: '1h' }
const twentyFourHour = { value: '24h', label: '24h' }

export const errorTrackingLogic = kea<errorTrackingLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingLogic']),

    actions({
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setOrder: (order: ErrorTrackingOrder) => ({ order }),
        setFilterGroup: (filterGroup: UniversalFiltersGroup) => ({ filterGroup }),
        setFilterTestAccounts: (filterTestAccounts: boolean) => ({ filterTestAccounts }),
        setSparklineSelectedPeriod: (period: string) => ({ period }),
        _setSparklineOptions: (options: LemonSegmentedButtonOption<string>[]) => ({ options }),
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
            twentyFourHour.value,
            { persist: true },
            {
                setSparklineSelection: (_, { selection }) => selection,
            },
        ],
        sparklineOptions: [
            [twentyFourHour, oneHour] as LemonSegmentedButtonOption<string>[],
            { persist: true },
            {
                _setSparklineOptions: (_, { options }) => options,
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        setDateRange: ({ dateRange: { date_from } }) => {
            const options: LemonSegmentedButtonOption<string>[] = []

            // today and last 24 hours
            if (date_from === 'dStart' || date_from === '-24h') {
                options.push(twentyFourHour, oneHour)
            } else if (date_from) {
                const value = date_from?.replace('-', '')
                options.push({ value: value, label: value }, twentyFourHour)
            }

            const possibleValues = options.map((o) => o.value)

            if (!possibleValues.includes(values.sparklineSelection)) {
                actions.setSparklineSelectedPeriod(options[0].value)
            }

            actions._setSparklineOptions(options)
        },
    })),
])
