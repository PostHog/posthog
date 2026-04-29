import { dayjs } from 'lib/dayjs'

import { ResolvedDateRangeResponse } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

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

// When an insight is grouped by month, the query's WHERE clause uses
// toStartOfInterval(date_from, month), so the first and last chart buckets cover the
// whole month. Expand the resolved range we show in the tooltip to match — otherwise
// "Last 12 months" from April 7 looks like it excludes April 1–6, which it doesn't.
// Scoped to month for now; weekly grouping has the same drift but is less visually
// jarring and isn't handled here.
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
    if (interval !== 'month') {
        return resolvedDateRange
    }
    // Parse the wall-clock portion only, so manipulation stays in the original tz.
    const [fromWall, fromTz] = splitTimezoneSuffix(resolvedDateRange.date_from)
    const [toWall, toTz] = splitTimezoneSuffix(resolvedDateRange.date_to)
    const from = dayjs.utc(fromWall).startOf('month')
    const to = dayjs.utc(toWall).endOf('month')
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

    const formatDate = (iso: string): { dateTime: string; tz: string } => {
        // YYYY-MM-DD HH:mm
        const dateTime = iso.slice(0, 16).replace('T', ' ')
        // timezone (+00:00, -08:00, +08:00)
        const tz = iso.endsWith('Z') ? '+00:00' : iso.slice(-6)
        return { dateTime, tz }
    }

    const from = formatDate(resolvedDateRange.date_from)
    const to = formatDate(resolvedDateRange.date_to)

    return `${from.dateTime} - ${to.dateTime} (${from.tz})`
}

export function formatLocalizedDate(): string {
    const localLang = navigator.language || document.documentElement.lang || 'en-US'
    const usDateLocales = ['en-US', 'en-CA']

    return usDateLocales.some((usLocale) => localLang.startsWith(usLocale)) ? 'MMM DD' : 'DD MMM'
}
