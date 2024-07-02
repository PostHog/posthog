import { LemonSegmentedButtonOption } from '@posthog/lemon-ui'
import { actions, kea, listeners, path, reducers } from 'kea'
import { UniversalFiltersGroup } from 'lib/components/UniversalFilters/UniversalFilters'

import { DateRange, ErrorTrackingOrder } from '~/queries/schema'
import { FilterLogicalOperator } from '~/types'

import type { errorTrackingLogicType } from './errorTrackingLogicType'

export type ErrorTrackingSparklineConfig = { period: number; unit: 'hour' | 'day'; multiplier: number }
type SparklineOption = LemonSegmentedButtonOption<string> & ErrorTrackingSparklineConfig

const SPARKLINE_OPTIONS = {
    '1h': { period: 60, unit: 'minute', value: '1h', label: '1h', multiplier: 1 },
    '24h': { value: '24h', label: '24h', period: 24, unit: 'hour', multiplier: 1 },
    '7d': { value: '7d', label: '7d', period: 7, unit: 'hour', multiplier: 8 },
    '14d': { value: '14d', label: '14d', period: 14, unit: 'hour', multiplier: 2 },
}

export const errorTrackingLogic = kea<errorTrackingLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingLogic']),

    actions({
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setOrder: (order: ErrorTrackingOrder) => ({ order }),
        setFilterGroup: (filterGroup: UniversalFiltersGroup) => ({ filterGroup }),
        setFilterTestAccounts: (filterTestAccounts: boolean) => ({ filterTestAccounts }),
        setSparklineSelection: (selection: SparklineOption) => ({ selection }),
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
            SPARKLINE_OPTIONS['24h'] as SparklineOption,
            { persist: true },
            {
                setSparklineSelection: (_, { selection }) => selection,
            },
        ],
        sparklineOptions: [
            [SPARKLINE_OPTIONS['24h'], SPARKLINE_OPTIONS['7d']] as SparklineOption[],
            { persist: true },
            {
                _setSparklineOptions: (_, { options }) => options,
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        setDateRange: ({ dateRange: { date_from, date_to } }) => {
            const options = []

            // today and yesterday
            if (date_from === 'dStart' || (date_from === '-1dStart' && date_to === '-1dEnd') || date_from === '-24h') {
                options.push(SPARKLINE_OPTIONS['24h'], SPARKLINE_OPTIONS['1h'])
            } else {
                const period = Number(date_from?.replace(/-|h|d/g, ''))
                options.push(
                    {
                        period: period,
                        unit: period === 7 ? 'hour' : 'day',
                        value: `${period}d`,
                        label: `${period}d`,
                        multiplier: period === 7 ? 3 : 1,
                    },
                    SPARKLINE_OPTIONS['24h']
                )
            }

            const possibleValues = options.map((o) => o.value)

            if (!possibleValues.includes(values.sparklineSelection.value)) {
                actions.setSparklineSelection(options[0])
            }

            actions._setSparklineOptions(options)
        },
    })),
])
