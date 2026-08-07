import { dayjs } from 'lib/dayjs'

import { ResolvedDateRangeResponse } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

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

export interface DayJSDateRange {
    start: dayjs.Dayjs
    end: dayjs.Dayjs
}

/**
 * Get week boundaries for a reference date constrained by a date range.
 */
export function getConstrainedWeekRange(
    referenceDate: dayjs.Dayjs,
    dateRangeBoundary?: DayJSDateRange | null,
    weekStartDay: number = 0 // 0 for Sunday, 1 for Monday
): DayJSDateRange {
    dayjs.updateLocale('en', {
        weekStart: weekStartDay,
    })

    // Prevent an edge case where the reference date is not set to the start of the week
    // This can happen when the data is cached and the weekStartDay changes
    if ([0, 1].includes(referenceDate.day()) && referenceDate.day() !== weekStartDay) {
        // adjust the reference date to the start of the week
        referenceDate = referenceDate.add(weekStartDay - referenceDate.day(), 'day')
    }

    const weekStart = referenceDate.startOf('week')
    const weekEnd = referenceDate.endOf('week')

    if (dateRangeBoundary && dateRangeBoundary.start.isValid() && dateRangeBoundary.end.isValid()) {
        return {
            start:
                dateRangeBoundary.start.isAfter(weekStart) && dateRangeBoundary.start.isBefore(weekEnd)
                    ? dateRangeBoundary.start
                    : weekStart,
            end:
                dateRangeBoundary.end.isBefore(weekEnd) && dateRangeBoundary.end.isAfter(weekStart)
                    ? dateRangeBoundary.end
                    : weekEnd,
        }
    }

    return {
        start: weekStart,
        end: weekEnd,
    }
}

// When an insight is grouped by month/quarter/year, the query's WHERE clause uses
// toStartOfInterval(date_from, <interval>), so the first and last chart buckets cover the
// whole period. Expand the resolved range we show in the tooltip to match — otherwise
// "Last 12 months" from April 7 looks like it excludes April 1–6, which it doesn't.
// Weekly grouping has the same drift but is less visually jarring and isn't handled here.
const TZ_SUFFIX_RE = /([+-]\d{2}:\d{2}|Z)$/

function splitTimezoneSuffix(iso: string): [string, string] {
    const match = iso.match(TZ_SUFFIX_RE)
    if (!match) {
        return [iso, '']
    }
    const suffix = match[0] === 'Z' ? '+00:00' : match[0]
    return [iso.slice(0, -match[0].length), suffix]
}

export function alignResolvedDateRangeToInterval(
    resolvedDateRange: ResolvedDateRangeResponse | null | undefined,
    interval: IntervalType | null | undefined
): ResolvedDateRangeResponse | undefined {
    if (!resolvedDateRange?.date_from || !resolvedDateRange?.date_to) {
        return undefined
    }
    if (interval !== 'month' && interval !== 'quarter' && interval !== 'year') {
        return resolvedDateRange
    }
    // Parse the wall-clock portion only, so manipulation stays in the original tz.
    const [fromWall, fromTz] = splitTimezoneSuffix(resolvedDateRange.date_from)
    const [toWall, toTz] = splitTimezoneSuffix(resolvedDateRange.date_to)
    const from = dayjs.utc(fromWall).startOf(interval)
    const to = dayjs.utc(toWall).endOf(interval)
    return {
        date_from: from.format('YYYY-MM-DDTHH:mm:ss') + fromTz,
        date_to: to.format('YYYY-MM-DDTHH:mm:ss') + toTz,
    }
}

export function formatResolvedDateRange(
    resolvedDateRange: ResolvedDateRangeResponse | null | undefined
): string | undefined {
    if (!resolvedDateRange || !resolvedDateRange.date_from || !resolvedDateRange.date_to) {
        return
    }

    const formatIsoParts = (iso: string): { dateTime: string; tz: string } => {
        // YYYY-MM-DD HH:mm
        const dateTime = iso.slice(0, 16).replace('T', ' ')
        // timezone (+00:00, -08:00, +08:00)
        const tz = iso.endsWith('Z') ? '+00:00' : iso.slice(-6)
        return { dateTime, tz }
    }

    const from = formatIsoParts(resolvedDateRange.date_from)
    const to = formatIsoParts(resolvedDateRange.date_to)

    return `${from.dateTime} - ${to.dateTime} (${from.tz})`
}

export function formatLocalizedDate(): string {
    const localLang = navigator.language || document.documentElement.lang || 'en-US'
    const usDateLocales = ['en-US', 'en-CA']

    return usDateLocales.some((usLocale) => localLang.startsWith(usLocale)) ? 'MMM DD' : 'DD MMM'
}

/** Parse a date string into a Dayjs in the given timezone, browser-tz-independent.
 *
 * - Strings without explicit timezone info ("2026-03-08", "2026-03-08 14:00:00")
 *   are treated as wall-clock time in the given timezone. Strings from ClickHouse
 *   already have wall-clock digits in the project timezone because ClickHouse applies
 *   toTimeZone before truncation, and date-only buckets from the trends backend
 *   have no time component to convert.
 * - Strings with explicit timezone info (trailing "Z" or "±HH:MM") are real instants;
 *   parse them as such and convert into the requested timezone.
 *
 * Don't use the `dayjs.utc(...).tz(timezone, true)` shape: keepLocalTime reads the
 * **system** local representation of the underlying instant, not the UTC
 * representation, so when the browser tz is east of UTC (e.g. Berlin, Tokyo) the
 * calendar date shifts back by one day. */
export function parseDateInTimezone(dateStr: string, timezone: string): dayjs.Dayjs {
    const hasExplicitTz = /([Zz]|[+-]\d{2}:?\d{2})$/.test(dateStr)
    try {
        if (hasExplicitTz) {
            const instant = dayjs(dateStr)
            return instant.isValid() ? instant.tz(timezone) : dayjs(null)
        }
        return dayjs.tz(dateStr, timezone)
    } catch {
        return dayjs(null)
    }
}

/** Whole seconds elapsed from an ISO start timestamp to a reference `now` (ms epoch).
 * Returns 0 for an unparseable start or a `now` that precedes it, so callers never
 * surface a negative or NaN duration. */
export function elapsedSecondsFrom(startedAt: string, now: number): number {
    const started = new Date(startedAt).getTime()
    if (Number.isNaN(started)) {
        return 0
    }
    return Math.max(0, Math.floor((now - started) / 1000))
}
