import { useActions, useValues } from 'kea'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import type { DateMappingOption } from '~/types'

import {
    MODELS_USAGE_RANGE_DAYS,
    modelsUsageRangeDescription,
    modelsUsageRangeLabel,
    modelsUsageRelativeDateFrom,
} from './modelsUsageDateRanges'
import { modelsUsageLogic } from './modelsUsageLogic'

const DATE_OPTIONS: DateMappingOption[] = MODELS_USAGE_RANGE_DAYS.map((days) => ({
    key: modelsUsageRangeLabel(days),
    values: [modelsUsageRelativeDateFrom(days)],
    getFormattedDate: (date) => modelsUsageRangeDescription(days, date),
    defaultInterval: 'day',
}))

export function ModelsUsageDateFilter(): JSX.Element {
    const { dateFrom, dateTo, usageLoading, jobsLoading } = useValues(modelsUsageLogic)
    const { setDateRange } = useActions(modelsUsageLogic)

    return (
        <div data-attr="models-usage-date-range">
            <DateFilter
                dateFrom={dateFrom}
                dateTo={dateTo}
                onChange={setDateRange}
                dateOptions={DATE_OPTIONS}
                showRollingRangePicker={false}
                forceGranularity="day"
                disabled={usageLoading || jobsLoading}
            />
        </div>
    )
}
