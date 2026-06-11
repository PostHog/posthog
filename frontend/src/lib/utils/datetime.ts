import { dayjs } from 'lib/dayjs'

export function humanFriendlyDetailedTime(
    date: dayjs.Dayjs | string | null | undefined,
    formatDate = 'MMMM DD, YYYY',
    formatTime = 'h:mm:ss A',
    options: { timestampStyle?: 'relative' | 'absolute' } = { timestampStyle: 'relative' }
): string {
    if (!date) {
        return 'Never'
    }
    const parsedDate = dayjs(date)

    if (options.timestampStyle === 'absolute') {
        return parsedDate.format(`${formatDate} ${formatTime}`)
    }

    const today = dayjs().startOf('day')
    const yesterday = today.clone().subtract(1, 'days').startOf('day')
    if (parsedDate.isSame(dayjs(), 'm')) {
        return 'Just now'
    }
    let formatString: string
    if (parsedDate.isSame(today, 'd')) {
        formatString = `[Today] ${formatTime}`
    } else if (parsedDate.isSame(yesterday, 'd')) {
        formatString = `[Yesterday] ${formatTime}`
    } else {
        formatString = `${formatDate} ${formatTime}`
    }
    return parsedDate.format(formatString)
}

export function detailedTime(date: dayjs.Dayjs | string | null | undefined): string {
    if (!date) {
        return ''
    }
    return dayjs(date).format('MMMM DD, YYYY h:mm:ss A')
}

export function determineDifferenceType(
    firstDate: dayjs.Dayjs | string,
    secondDate: dayjs.Dayjs | string
): 'year' | 'month' | 'week' | 'day' | 'hour' | 'minute' | 'second' {
    const first = dayjs(firstDate)
    const second = dayjs(secondDate)
    if (first.diff(second, 'years') !== 0) {
        return 'year'
    } else if (first.diff(second, 'months') !== 0) {
        return 'month'
    } else if (first.diff(second, 'weeks') !== 0) {
        return 'week'
    } else if (first.diff(second, 'days') !== 0) {
        return 'day'
    } else if (first.diff(second, 'hours') !== 0) {
        return 'hour'
    }
    return 'minute'
}

export const DATE_FORMAT = 'MMMM D, YYYY'

export const DATE_TIME_FORMAT = 'MMMM D, YYYY HH:mm:ss'

export const DATE_FORMAT_WITHOUT_YEAR = 'MMMM D'

export const DATE_FORMAT_WITHOUT_DAY = 'HH:mm:ss'

export const formatDate = (date: dayjs.Dayjs, format?: string): string => {
    return date.format(format ?? DATE_FORMAT)
}

export const formatDateTime = (date: dayjs.Dayjs, format?: string): string => {
    return date.format(format ?? DATE_TIME_FORMAT)
}

export const formatDateRange = (dateFrom: dayjs.Dayjs, dateTo: dayjs.Dayjs, format?: string): string => {
    let formatFrom = format ?? DATE_FORMAT
    const formatTo = format ?? DATE_FORMAT
    if ((!format || format === DATE_FORMAT) && dateFrom.year() === dateTo.year()) {
        formatFrom = DATE_FORMAT_WITHOUT_YEAR
    }
    return `${dateFrom.format(formatFrom)} - ${dateTo.format(formatTo)}`
}

export const formatDateTimeRange = (dateFrom: dayjs.Dayjs, dateTo: dayjs.Dayjs): string => {
    const MONTHDAY = 'MMMM D'
    const COMMA = ', '
    const YEAR = 'YYYY '
    const TIME = 'HH:mm'
    const SECONDS = ':ss'

    let fromComponents = [MONTHDAY, COMMA, YEAR, TIME, SECONDS]
    let toComponents = [MONTHDAY, COMMA, YEAR, TIME, SECONDS]
    if (dateFrom.year() === dateTo.year()) {
        toComponents = toComponents.filter((x) => x !== YEAR)
        if (dateTo.year() === dayjs().year()) {
            fromComponents = fromComponents.filter((x) => x !== YEAR)
        }

        if (dateFrom.isSame(dateTo, 'day')) {
            toComponents = toComponents.filter((x) => x !== MONTHDAY)
            toComponents = toComponents.filter((x) => x !== COMMA)
            if (dateFrom.isSame(dayjs(), 'day')) {
                fromComponents = fromComponents.filter((x) => x !== MONTHDAY)
                fromComponents = fromComponents.filter((x) => x !== COMMA)
            }
        }

        if (dateFrom.isSame(dayjs(dateFrom).startOf('day')) && dateTo.isSame(dayjs(dateTo).startOf('day'))) {
            fromComponents = fromComponents.filter((x) => x !== TIME)
            toComponents = toComponents.filter((x) => x !== TIME)
        }

        if (dateFrom.second() === 0 && dateTo.second() === 0) {
            fromComponents = fromComponents.filter((x) => x !== SECONDS)
            toComponents = toComponents.filter((x) => x !== SECONDS)
        }

        if (!fromComponents.includes(YEAR) && !fromComponents.includes(TIME)) {
            fromComponents = fromComponents.filter((x) => x !== COMMA)
        }

        if (!toComponents.includes(YEAR) && !toComponents.includes(TIME)) {
            toComponents = toComponents.filter((x) => x !== COMMA)
        }
    }
    return `${dateFrom.format(fromComponents.join(''))} - ${dateTo.format(toComponents.join(''))}`
}

export const isDate = /([0-9]{4}-[0-9]{2}-[0-9]{2})/

export function getFormattedLastWeekDate(lastDay: dayjs.Dayjs = dayjs()): string {
    return formatDateRange(lastDay.subtract(7, 'week'), lastDay.endOf('d'))
}

// Compute the ISO week string for a given date
// Useful above to show the toast once per week
export function getISOWeekString(date = new Date()): string {
    const dayjs_date = dayjs(date)

    const year = dayjs_date.year()
    const week = dayjs_date.week()

    return `${year}-W${week}`
}
