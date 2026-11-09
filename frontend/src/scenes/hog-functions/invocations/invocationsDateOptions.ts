import { dayjs } from 'lib/dayjs'
import { CUSTOM_OPTION_KEY } from 'lib/utils/dateFilters'
import { DATE_TIME_FORMAT, formatDateRange } from 'lib/utils/datetime'

import { DateMappingOption } from '~/types'

/**
 * Preset windows mirroring the Logs viewer — covers minute-level scoping
 * (5m / 30m / 1h) plus the longer windows the table already supported.
 * Pairs with `allowTimePrecision` + `allowFixedRangeWithTime` so custom
 * ranges accept minute-precision timestamps.
 */
export const INVOCATIONS_DATE_OPTIONS: DateMappingOption[] = [
    { key: CUSTOM_OPTION_KEY, values: [] },
    {
        key: 'Last 5 minutes',
        values: ['-5M'],
        getFormattedDate: (date) => date.subtract(5, 'minute').format(DATE_TIME_FORMAT),
        defaultInterval: 'minute',
    },
    {
        key: 'Last 30 minutes',
        values: ['-30M'],
        getFormattedDate: (date) => date.subtract(30, 'minute').format(DATE_TIME_FORMAT),
        defaultInterval: 'minute',
    },
    {
        key: 'Last 1 hour',
        values: ['-1h'],
        getFormattedDate: (date: dayjs.Dayjs) => formatDateRange(date.subtract(1, 'h'), date),
        defaultInterval: 'hour',
    },
    {
        key: 'Last 4 hours',
        values: ['-4h'],
        getFormattedDate: (date: dayjs.Dayjs) => formatDateRange(date.subtract(4, 'h'), date),
        defaultInterval: 'hour',
    },
    {
        key: 'Last 24 hours',
        values: ['-24h'],
        getFormattedDate: (date: dayjs.Dayjs) => formatDateRange(date.subtract(24, 'h'), date.endOf('d')),
        defaultInterval: 'hour',
    },
    {
        key: 'Last 7 days',
        values: ['-7d'],
        getFormattedDate: (date: dayjs.Dayjs) => formatDateRange(date.subtract(7, 'd'), date.endOf('d')),
        defaultInterval: 'day',
    },
    {
        key: 'Last 30 days',
        values: ['-30d'],
        getFormattedDate: (date: dayjs.Dayjs) => formatDateRange(date.subtract(30, 'd'), date.endOf('d')),
        defaultInterval: 'day',
    },
]
