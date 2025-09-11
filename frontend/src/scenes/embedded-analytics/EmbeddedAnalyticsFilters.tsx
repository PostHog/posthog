import { useActions, useValues } from 'kea'

import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { dayjs } from 'lib/dayjs'
import { formatDateRange } from 'lib/utils'

import { DateMappingOption } from '~/types'

import { embeddedAnalyticsLogic } from './embeddedAnalyticsLogic'

const embeddedAnalyticsDateMapping: DateMappingOption[] = [
    {
        key: 'Last 24 hours',
        values: ['-24h'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(24, 'h'), date.endOf('d')),
        defaultInterval: 'hour',
    },
    {
        key: 'Last 48 hours',
        values: ['-48h'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(48, 'h'), date.endOf('d')),
        defaultInterval: 'hour',
    },
    {
        key: 'Last 7 days',
        values: ['-7d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(7, 'd'), date.endOf('d')),
        defaultInterval: 'day',
    },
    {
        key: 'Last 14 days',
        values: ['-14d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(14, 'd'), date.endOf('d')),
        defaultInterval: 'day',
    },
    {
        key: 'Last 30 days',
        values: ['-30d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(30, 'd'), date.endOf('d')),
        defaultInterval: 'day',
    },
    {
        key: 'Last 90 days',
        values: ['-90d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(90, 'd'), date.endOf('d')),
        defaultInterval: 'day',
    },
    {
        key: 'Year to date',
        values: ['yStart'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.startOf('y'), date.endOf('d')),
        defaultInterval: 'day',
    },
]

const RequestNameBreakdownToggle = (): JSX.Element => {
    const { requestNameBreakdownEnabled } = useValues(embeddedAnalyticsLogic)
    const { setRequestNameBreakdownEnabled } = useActions(embeddedAnalyticsLogic)

    return (
        <LemonButton
            onClick={() => setRequestNameBreakdownEnabled(!requestNameBreakdownEnabled)}
            type="secondary"
            size="small"
        >
            Breakdown by request name <LemonSwitch checked={requestNameBreakdownEnabled} className="ml-1" />
        </LemonButton>
    )
}

export const EmbeddedAnalyticsFilters = ({ tabs }: { tabs?: JSX.Element }): JSX.Element => {
    const { dateFilter } = useValues(embeddedAnalyticsLogic)
    const { setDates } = useActions(embeddedAnalyticsLogic)

    return (
        <FilterBar
            top={tabs}
            left={
                <>
                    <DateFilter
                        dateFrom={dateFilter.dateFrom}
                        dateTo={dateFilter.dateTo}
                        onChange={setDates}
                        forceGranularity="day"
                        dateOptions={embeddedAnalyticsDateMapping}
                    />
                    <RequestNameBreakdownToggle />
                </>
            }
        />
    )
}
