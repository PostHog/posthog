import { useActions, useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { FilterBar } from 'lib/components/FilterBar'
import { dayjs } from 'lib/dayjs'
import { formatDateRange } from 'lib/utils'

import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { DateMappingOption } from '~/types'

import { customerAnalyticsSceneLogic } from './customerAnalyticsSceneLogic'

const DATE_FILTER_DATE_OPTIONS: DateMappingOption[] = [
    { key: CUSTOM_OPTION_KEY, values: [] },
    {
        key: 'Last 7 days',
        values: ['-7d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(7, 'days'), date),
        defaultInterval: 'day',
    },
    {
        key: 'Last 14 days',
        values: ['-14d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(14, 'days'), date),
        defaultInterval: 'day',
    },
    {
        key: 'Last 30 days',
        values: ['-30d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(30, 'days'), date),
        defaultInterval: 'day',
    },
    {
        key: 'Last 90 days',
        values: ['-90d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(90, 'days'), date),
        defaultInterval: 'day',
    },
    {
        key: 'Last 180 days',
        values: ['-180d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(180, 'days'), date),
        defaultInterval: 'week',
    },
    {
        key: 'This month',
        values: ['mStart', 'mEnd'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.startOf('m'), date.endOf('m')),
        defaultInterval: 'day',
    },
    {
        key: 'Last month',
        values: ['-1mStart', '-1mEnd'],
        getFormattedDate: (date: dayjs.Dayjs): string =>
            formatDateRange(date.subtract(1, 'month').startOf('month'), date.subtract(1, 'month').endOf('month')),
        defaultInterval: 'day',
    },
    {
        key: 'Year to date',
        values: ['yStart'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.startOf('y'), date),
        defaultInterval: 'week',
    },
    {
        key: 'All time',
        values: ['all'],
        defaultInterval: 'month',
    },
]

export function CustomerAnalyticsFilters(): JSX.Element {
    const {
        dateFilter: { dateTo, dateFrom },
    } = useValues(customerAnalyticsSceneLogic)

    const { setDates } = useActions(customerAnalyticsSceneLogic)

    return (
        <FilterBar
            left={
                <DateFilter
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    onChange={setDates}
                    dateOptions={DATE_FILTER_DATE_OPTIONS}
                    size="small"
                />
            }
            right={
                <Tooltip title="Refresh data">
                    <ReloadAll />
                </Tooltip>
            }
        />
    )
}
