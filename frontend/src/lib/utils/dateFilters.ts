import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { Dayjs, dayjs } from 'lib/dayjs'
import { DATE_FORMAT, formatDate, formatDateRange, formatDateTimeRange, isDate } from 'lib/utils/datetime'
import { UnexpectedNeverError } from 'lib/utils/guards'

import { DateMappingOption, IntervalType } from '~/types'

/** Returns the start of the current week, respecting the team's week start day (0=Sunday, 1=Monday). */
function startOfWeek(date: dayjs.Dayjs, weekStartDay?: number | null): dayjs.Dayjs {
    const start = weekStartDay === 1 ? 1 : 0
    return date.subtract((date.day() - start + 7) % 7, 'day').startOf('day')
}

export const dateMapping: DateMappingOption[] = [
    { key: CUSTOM_OPTION_KEY, values: [] },
    {
        key: 'Today',
        values: ['dStart'],
        getFormattedDate: (date: dayjs.Dayjs): string => date.startOf('d').format(DATE_FORMAT),
        defaultInterval: 'hour',
    },
    {
        key: 'Yesterday',
        values: ['-1dStart', '-1dEnd'],
        getFormattedDate: (date: dayjs.Dayjs): string => date.subtract(1, 'd').format(DATE_FORMAT),
        defaultInterval: 'hour',
    },
    {
        key: 'Last hour',
        values: ['-1h'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(1, 'h'), date),
        defaultInterval: 'minute',
    },
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
        inactive: true,
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
        key: 'Last 180 days',
        values: ['-180d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(180, 'd'), date.endOf('d')),
        defaultInterval: 'month',
    },

    {
        key: 'Last week',
        values: ['-1wStart', '-1wEnd'],
        getFormattedDate: (date: dayjs.Dayjs, _format?: string, weekStartDay?: number): string => {
            const lastWeekStart = startOfWeek(date, weekStartDay).subtract(7, 'day')
            return formatDateRange(lastWeekStart, lastWeekStart.add(6, 'day').endOf('d'))
        },
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
        key: 'This week',
        values: ['wStart'],
        getFormattedDate: (date: dayjs.Dayjs, _format?: string, weekStartDay?: number): string =>
            formatDateRange(startOfWeek(date, weekStartDay), date.endOf('d')),
        defaultInterval: 'day',
    },
    {
        key: 'This month',
        values: ['mStart'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.startOf('month'), date.endOf('month')),
        defaultInterval: 'day',
    },
    {
        key: 'Year to date',
        values: ['yStart'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.startOf('y'), date.endOf('d')),
        defaultInterval: 'month',
    },
    {
        key: 'All time',
        values: ['all'],
        defaultInterval: 'month',
    },
]

const dateOptionsMap = {
    y: 'year',
    q: 'quarter',
    m: 'month',
    w: 'week',
    d: 'day',
    h: 'hour',
    M: 'minute',
    s: 'second',
} as const

export function dateFilterToText(
    dateFrom: string | dayjs.Dayjs | null | undefined,
    dateTo: string | dayjs.Dayjs | null | undefined,
    defaultValue: string | null,
    dateOptions: DateMappingOption[] = dateMapping,
    isDateFormatted: boolean = false,
    dateFormat: string = DATE_FORMAT,
    startOfRange: boolean = false,
    weekStartDay?: number
): string | null {
    if (dayjs.isDayjs(dateFrom) && dayjs.isDayjs(dateTo)) {
        return formatDateRange(dateFrom, dateTo, dateFormat)
    }
    dateFrom = (dateFrom || undefined) as string | undefined
    dateTo = (dateTo || undefined) as string | undefined

    if (isDate.test(dateFrom || '') && isDate.test(dateTo || '')) {
        if (isDateFormatted) {
            return formatDateRange(dayjs(dateFrom, 'YYYY-MM-DD'), dayjs(dateTo, 'YYYY-MM-DD'))
        }
        if (dateFrom?.includes('T') || dateTo?.includes('T')) {
            // Parse each date individually - ISO 8601 datetimes (with T) use native parsing
            // to correctly handle seconds/milliseconds, plain dates use 'YYYY-MM-DD'
            const parsedFrom = dateFrom?.includes('T') ? dayjs(dateFrom) : dayjs(dateFrom, 'YYYY-MM-DD')
            const parsedTo = dateTo?.includes('T') ? dayjs(dateTo) : dayjs(dateTo, 'YYYY-MM-DD')
            return formatDateTimeRange(parsedFrom, parsedTo)
        }
        return `${dateFrom} - ${dateTo}`
    }

    // From date to today
    if (isDate.test(dateFrom || '') && !isDate.test(dateTo || '')) {
        const days = dayjs().diff(dayjs(dateFrom), 'days')
        if (days > 366) {
            return isDateFormatted ? `${dateFrom} - today` : formatDateRange(dayjs(dateFrom), dayjs())
        } else if (days > 0) {
            return isDateFormatted ? formatDateRange(dayjs(dateFrom), dayjs()) : `Last ${days} days`
        } else if (days === 0) {
            return isDateFormatted ? dayjs(dateFrom).format(dateFormat) : `Today`
        }
        return isDateFormatted ? `${dayjs(dateFrom).format(dateFormat)} - ` : `Starting from ${dateFrom}`
    }

    for (const { key, values, getFormattedDate } of dateOptions) {
        if (values[0] === dateFrom && values[1] === dateTo && key !== CUSTOM_OPTION_KEY) {
            return isDateFormatted && getFormattedDate ? getFormattedDate(dayjs(), dateFormat, weekStartDay) : key
        }
    }

    if (dateFrom) {
        const dateOption = dateOptionsMap[dateFrom.slice(-1) as keyof typeof dateOptionsMap]
        const counter = parseInt(dateFrom.slice(1, -1))
        if (dateOption && counter) {
            let date = null
            switch (dateOption) {
                case 'year':
                    date = dayjs().subtract(counter, 'y')
                    break
                case 'hour':
                    date = dayjs().subtract(counter, 'h')
                    break
                case 'quarter':
                    date = dayjs().subtract(counter * 3, 'M')
                    break
                case 'month':
                    date = dayjs().subtract(counter, 'M')
                    break
                case 'week':
                    date = dayjs().subtract(counter * 7, 'd')
                    break
                case 'minute':
                    date = dayjs().subtract(counter, 'm')
                    break
                case 'second':
                    date = dayjs().subtract(counter, 's')
                    break
                default:
                    date = dayjs().subtract(counter, 'd')
                    break
            }
            if (isDateFormatted) {
                return formatDateRange(date, dayjs().endOf('d'))
            } else if (startOfRange) {
                return formatDate(date, dateFormat)
            }
            return `Last ${counter} ${dateOption}${counter > 1 ? 's' : ''}`
        }
    }

    return defaultValue
}

// Converts a dateFrom string ("-2w") into english: "2 weeks"
export function dateFromToText(dateFrom: string): string | undefined {
    const dateOption: (typeof dateOptionsMap)[keyof typeof dateOptionsMap] =
        dateOptionsMap[dateFrom.slice(-1) as keyof typeof dateOptionsMap]
    const counter = parseInt(dateFrom.slice(1, -1))
    if (dateOption && counter) {
        return `${counter} ${dateOption}${counter > 1 ? 's' : ''}`
    }
    return undefined
}

export type DateComponents = {
    amount: number
    unit: (typeof dateOptionsMap)[keyof typeof dateOptionsMap]
    clip: 'Start' | 'End'
}

export const isStringDateRegex = /^([-+]?)([0-9]*)([hdwmqyMs])(|Start|End)$/

export function dateStringToComponents(date: string | null): DateComponents | null {
    if (!date) {
        return null
    }
    const matches = date.match(isStringDateRegex)
    if (!matches) {
        return null
    }
    const [, sign, rawAmount, rawUnit, clip] = matches
    const amount = rawAmount ? parseInt(sign + rawAmount) : 0
    const unit = dateOptionsMap[rawUnit as keyof typeof dateOptionsMap] || 'day'
    return { amount, unit, clip: clip as 'Start' | 'End' }
}

export function componentsToDayJs(
    { amount, unit, clip }: DateComponents,
    offset?: Dayjs,
    timezone: string = 'UTC'
): Dayjs {
    const dayjsInstance = offset ?? dayjs().tz(timezone)
    let response: dayjs.Dayjs
    switch (unit) {
        case 'year':
            response = dayjsInstance.add(amount, 'year')
            break
        case 'quarter':
            response = dayjsInstance.add(amount * 3, 'month')
            break
        case 'month':
            response = dayjsInstance.add(amount, 'month')
            break
        case 'week':
            response = dayjsInstance.add(amount * 7, 'day')
            break
        case 'day':
            response = dayjsInstance.add(amount, 'day')
            break
        case 'hour':
            response = dayjsInstance.add(amount, 'hour')
            break
        case 'minute':
            response = dayjsInstance.add(amount, 'minute')
            break
        case 'second':
            response = dayjsInstance.add(amount, 'second')
            break
        default:
            throw new UnexpectedNeverError(unit)
    }

    if (clip === 'Start') {
        return response.startOf(unit)
    } else if (clip === 'End') {
        return response.endOf(unit)
    }
    return response
}

/** Convert a string like "-30d" or "2022-02-02" or "-1mEnd" to `Dayjs().startOf('day')` */
export function dateStringToDayJs(date: string | null, timezone: string = 'UTC'): dayjs.Dayjs | null {
    if (isDate.test(date || '')) {
        return dayjs.tz(date, timezone)
    }
    const dateComponents = dateStringToComponents(date)
    if (!dateComponents) {
        return null
    }
    // Calendar units anchor at the start of today; sub-day units are rolling
    // windows from now ("-30M" must mean 30 minutes ago, not today 00:00 minus
    // 30 minutes = yesterday 23:30) — matching the backend's relative_date_parse.
    const isSubDay = ['hour', 'minute', 'second'].includes(dateComponents.unit)
    const offset: dayjs.Dayjs = isSubDay ? dayjs().tz(timezone) : dayjs().tz(timezone).startOf('day')
    const response = componentsToDayJs(dateComponents, offset, timezone)
    return response
}

export function isValidRelativeOrAbsoluteDate(date: string): boolean {
    if (isStringDateRegex.test(date)) {
        return true
    }
    if (dayjs(date).isValid()) {
        return true
    }
    if (date === 'all') {
        return true
    }
    return false
}

export const getDefaultInterval = (dateFrom: string | null, dateTo: string | null): IntervalType => {
    // use the default mapping if we can
    for (const mapping of dateMapping) {
        const mappingFrom = mapping.values[0] ?? null
        const mappingTo = mapping.values[1] ?? null
        if (mappingFrom === dateFrom && mappingTo === dateTo && mapping.defaultInterval) {
            return mapping.defaultInterval
        }
    }

    const parsedDateFrom = dateStringToComponents(dateFrom)
    const parsedDateTo = dateStringToComponents(dateTo)

    if (parsedDateFrom?.unit === 'hour' || parsedDateTo?.unit === 'hour') {
        return 'hour'
    }

    if (
        parsedDateFrom?.unit === 'day' ||
        parsedDateTo?.unit === 'day' ||
        dateFrom === 'mStart' ||
        dateFrom === 'wStart'
    ) {
        return 'day'
    }

    if (
        (parsedDateFrom?.unit === 'month' && parsedDateFrom.amount <= 3) ||
        (parsedDateTo?.unit === 'month' && parsedDateTo.amount <= 3) ||
        (parsedDateFrom?.unit === 'quarter' && parsedDateFrom.amount <= 1) ||
        (parsedDateTo?.unit === 'quarter' && parsedDateTo.amount <= 1)
    ) {
        return 'day'
    }

    if (
        parsedDateFrom?.unit === 'month' ||
        parsedDateTo?.unit === 'month' ||
        parsedDateFrom?.unit === 'quarter' ||
        parsedDateTo?.unit === 'quarter' ||
        parsedDateFrom?.unit === 'year' ||
        parsedDateTo?.unit === 'year' ||
        dateFrom === 'all'
    ) {
        return 'month'
    }

    const dateFromDayJs = dateStringToDayJs(dateFrom)
    const dateToDayJs = dateStringToDayJs(dateTo)

    const intervalMonths = dateFromDayJs?.diff(dateToDayJs, 'month')
    if (intervalMonths != null && Math.abs(intervalMonths) >= 2) {
        return 'month'
    }
    const intervalDays = dateFromDayJs?.diff(dateToDayJs, 'day')
    if (intervalDays != null && Math.abs(intervalDays) >= 14) {
        return 'week'
    }
    if (intervalDays != null && Math.abs(intervalDays) >= 2) {
        return 'day'
    }
    const intervalHours = dateFromDayJs?.diff(dateToDayJs, 'hour')
    if (intervalHours != null && Math.abs(intervalHours) >= 1) {
        return 'hour'
    }

    return 'day'
}

/* If the interval changes, check if it's compatible with the selected dates, and return new dates
 * from a map of sensible defaults if not */
export const areDatesValidForInterval = (
    interval: IntervalType,
    oldDateFrom: string | null,
    oldDateTo: string | null
): boolean => {
    const parsedOldDateFrom = dateStringToDayJs(oldDateFrom)
    const parsedOldDateTo = dateStringToDayJs(oldDateTo) || dayjs()

    if (oldDateFrom === 'all' || !parsedOldDateFrom) {
        return interval === 'month'
    } else if (interval === 'month') {
        return parsedOldDateTo.diff(parsedOldDateFrom, 'month') >= 2
    } else if (interval === 'week') {
        return parsedOldDateTo.diff(parsedOldDateFrom, 'week') >= 2
    } else if (interval === 'day') {
        const diff = parsedOldDateTo.diff(parsedOldDateFrom, 'day')
        return diff >= 2
    } else if (interval === 'hour') {
        return (
            parsedOldDateTo.diff(parsedOldDateFrom, 'hour') >= 2 &&
            parsedOldDateTo.diff(parsedOldDateFrom, 'hour') < 24 * 7 * 2 // 2 weeks
        )
    } else if (interval === 'minute') {
        return (
            parsedOldDateTo.diff(parsedOldDateFrom, 'minute') >= 2 &&
            parsedOldDateTo.diff(parsedOldDateFrom, 'minute') < 60 * 12 // 12 hours. picked based on max graph resolution
        )
    } else if (interval === 'second') {
        return (
            parsedOldDateTo.diff(parsedOldDateFrom, 'second') >= 2 &&
            parsedOldDateTo.diff(parsedOldDateFrom, 'second') < 60 * 60 // 1 hour
        )
    }
    throw new UnexpectedNeverError(interval)
}

const defaultDatesForInterval = {
    second: { dateFrom: '-1M', dateTo: null },
    minute: { dateFrom: '-1h', dateTo: null },
    hour: { dateFrom: '-24h', dateTo: null },
    day: { dateFrom: '-7d', dateTo: null },
    week: { dateFrom: '-28d', dateTo: null },
    month: { dateFrom: '-6m', dateTo: null },
}

export const updateDatesWithInterval = (
    interval: IntervalType,
    oldDateFrom: string | null,
    oldDateTo: string | null
): { dateFrom: string | null; dateTo: string | null } => {
    if (areDatesValidForInterval(interval, oldDateFrom, oldDateTo)) {
        return {
            dateFrom: oldDateFrom,
            dateTo: oldDateTo,
        }
    }
    return defaultDatesForInterval[interval]
}

export function is12HoursOrLess(dateFrom: string | undefined | null): boolean {
    if (!dateFrom) {
        return false
    }
    return dateFrom.search(/^-([0-9]|1[0-2])h$/) != -1
}

export function isLessThan2Days(dateFrom: string | undefined | null): boolean {
    if (!dateFrom) {
        return false
    }
    return dateFrom.search(/^-(4[0-7]|[0-3]?[0-9])h|[1-2]d$/) != -1
}
