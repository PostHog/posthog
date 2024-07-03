import { LemonSegmentedButtonOption } from '@posthog/lemon-ui'
import { actions, kea, listeners, path, reducers } from 'kea'
import { UniversalFiltersGroup } from 'lib/components/UniversalFilters/UniversalFilters'

import { DateRange, ErrorTrackingOrder } from '~/queries/schema'
import { FilterLogicalOperator } from '~/types'

import type { errorTrackingLogicType } from './errorTrackingLogicType'
import { ErrorTrackingSparklineConfig } from './queries'

type SparklineOption = LemonSegmentedButtonOption<string> & Pick<ErrorTrackingSparklineConfig, 'offsetHours'>

const oneHour = { value: '1h', label: '1h' }
const twentyFourHour = { value: '24h', label: '24h' }

export const errorTrackingLogic = kea<errorTrackingLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingLogic']),

    actions({
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setOrder: (order: ErrorTrackingOrder) => ({ order }),
        setFilterGroup: (filterGroup: UniversalFiltersGroup) => ({ filterGroup }),
        setFilterTestAccounts: (filterTestAccounts: boolean) => ({ filterTestAccounts }),
        setSparklineSelection: (selection: string) => ({ selection }),
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
        sparklineSelection: [
            '24h' as string,
            { persist: true },
            {
                setSparklineSelection: (_, { selection }) => selection,
            },
        ],
        sparklineOptions: [
            [twentyFourHour, oneHour] as SparklineOption[],
            { persist: true },
            {
                _setSparklineOptions: (_, { options }) => options,
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        setDateRange: ({ dateRange: { date_from, date_to } }) => {
            const options: SparklineOption[] = []

            // yesterday
            if (date_from === '-1dStart' && date_to === '-1dEnd') {
                options.push({ ...twentyFourHour, offsetHours: 24 }, { ...oneHour, offsetHours: 24 })
            } // today and last 24 hours
            else if (date_from === 'dStart' || date_from === '-24h') {
                options.push(twentyFourHour, oneHour)
            } else if (date_from) {
                const value = date_from?.replace('-', '')
                options.push({ value: value, label: value }, twentyFourHour)
            }

            const possibleValues = options.map((o) => o.value)

            if (!possibleValues.includes(values.sparklineSelection)) {
                actions.setSparklineSelection(options[0].value)
            }

            actions._setSparklineOptions(options)
        },
    })),
])
