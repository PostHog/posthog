import { dayjs } from 'lib/dayjs'

import { dateStringToDayJs } from '~/lib/utils'
import type { DateRange } from '~/queries/schema'
import type { IntervalType } from '~/types'

const DEFAULT_RELATIVE_START_DATE = '1d'

export const getDefaultComparisonPeriodRelativeStartDate = (
    dateRange: DateRange | null | undefined,
    interval: IntervalType | null | undefined
): string => {
    if (!dateRange || !dateRange.date_from || !interval) {
        return DEFAULT_RELATIVE_START_DATE
    }
    const truncateToStartOfDay = false
    const dateFrom = dateStringToDayJs(dateRange.date_from, truncateToStartOfDay)
    let dateTo
    if (dateRange.date_to) {
        dateTo = dateStringToDayJs(dateRange.date_to, truncateToStartOfDay)
    } else {
        dateTo = dayjs()
    }
    if (!dateFrom || !dateTo) {
        return DEFAULT_RELATIVE_START_DATE
    }
    // We want to compare insights with hour intervals to the same hours
    // of the preceding interval
    if (interval == 'hour') {
        interval = 'day'
    }
    // RollingDateRangeFilter doesn't support minutes
    if (interval == 'minute') {
        interval = 'hour'
    }
    let diffBetweenDates = dateTo.diff(dateFrom, interval, /* float= */ true)
    // This assumes that dateTo is now, so we need to look twice further to see
    // the previous interval
    diffBetweenDates = Math.ceil(diffBetweenDates) * 2
    return `-${diffBetweenDates}${interval[0]}`
}
