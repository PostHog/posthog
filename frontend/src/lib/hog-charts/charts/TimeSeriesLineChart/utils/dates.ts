import { dayjs, Dayjs } from 'lib/dayjs'

import { IntervalType } from '~/types'

interface CreateXAxisTickCallbackArgs {
    interval?: IntervalType
    allDays: (string | number)[]
    timezone: string
    numericTickPrefix?: string
}

type TickMode =
    | { type: 'month' }
    | { type: 'day' }
    | { type: 'monthly'; visibleBoundaries: Set<number> }
    | { type: 'hourly' }
    | { type: 'hourly-multi-day'; step: number; dayStartIndices: Set<number> }

export function createXAxisTickCallback({
    interval,
    allDays,
    timezone,
    numericTickPrefix,
}: CreateXAxisTickCallbackArgs): (value: string | number, index: number) => string | null {
    if (allDays.length === 0 || typeof allDays[0] !== 'string') {
        return (value) => (numericTickPrefix ? `${numericTickPrefix} ${String(value)}` : String(value))
    }

    const parsedDates = allDays.map((d) => parseDateForAxis(String(d), timezone))
    const first = parsedDates[0]
    const last = parsedDates[parsedDates.length - 1]

    if (!first?.isValid() || !last?.isValid()) {
        return (value) => String(value)
    }

    const resolvedInterval = interval ?? inferInterval(parsedDates)
    const mode = pickMode(resolvedInterval, parsedDates, first, last)

    return (_value: string | number, index: number): string | null => {
        const date = parsedDates[index]
        if (!date?.isValid()) {
            return String(_value)
        }

        if (!isTickVisible(mode, date, index)) {
            return null
        }

        return formatTick(mode, date, index)
    }
}

/** Parse a date string as a wall-clock time in the given timezone.
 *
 * All strings from ClickHouse — both datetime ("2026-03-08 14:00:00") and
 * date-only ("2026-03-08") — already have wall-clock digits in the project
 * timezone because ClickHouse applies toTimeZone before truncation. */
export function parseDateForAxis(dateStr: string, timezone: string): Dayjs {
    const hasTime = dateStr.includes(' ') || dateStr.includes('T')
    try {
        // Parse as UTC so the result is browser-timezone-independent.
        // (dayjs.tz(string, tz) goes through new Date() which uses the
        // browser's local timezone and can shift dates during DST.)
        const utc = hasTime ? dayjs.utc(dateStr) : dayjs.utc(dateStr + ' 00:00:00')
        // keepLocalTime: true preserves the wall-clock digits while
        // attaching the project timezone — no conversion arithmetic.
        return utc.isValid() ? utc.tz(timezone, true) : dayjs(null)
    } catch {
        return dayjs(null)
    }
}

function pickMode(interval: IntervalType, parsedDates: Dayjs[], first: Dayjs, last: Dayjs): TickMode {
    const spanMonths = (last.year() - first.year()) * 12 + last.month() - first.month()
    const spanDays = last.diff(first, 'day')

    if (interval === 'month') {
        return { type: 'month' }
    }
    if ((interval === 'day' || interval === 'week') && spanMonths >= 3) {
        return { type: 'monthly', visibleBoundaries: buildVisibleBoundaries(parsedDates) }
    }
    if (interval === 'day' || interval === 'week') {
        return { type: 'day' }
    }
    if (spanDays >= 2) {
        const step = spanDays <= 3 ? 6 : spanDays <= 7 ? 12 : 24
        const dayStartIndices = buildDayStartIndices(parsedDates)
        return { type: 'hourly-multi-day', step, dayStartIndices }
    }
    return { type: 'hourly' }
}

function isTickVisible(mode: TickMode, date: Dayjs, index: number): boolean {
    switch (mode.type) {
        case 'monthly':
            return mode.visibleBoundaries.has(index)
        case 'hourly-multi-day':
            if (mode.dayStartIndices.has(index)) {
                return true
            }
            // Only show intermediate time ticks (e.g. 06:00, 12:00) when there are few days
            return mode.dayStartIndices.size <= 3 && date.hour() % mode.step === 0
        default:
            return true
    }
}

function formatTick(mode: TickMode, date: Dayjs, index: number): string {
    switch (mode.type) {
        case 'month':
        case 'monthly':
            return formatMonthLabel(date)
        case 'day':
            return date.date() === 1 ? formatMonthLabel(date) : date.format('MMM D')
        case 'hourly-multi-day':
            return mode.dayStartIndices.has(index) ? date.format('MMM D') : date.format('HH:mm')
        case 'hourly':
            return date.format('HH:mm')
    }
}

function formatMonthLabel(date: Dayjs): string {
    if (date.month() === 0) {
        return String(date.year())
    }
    return date.format('MMMM')
}

function inferInterval(parsedDates: Dayjs[]): IntervalType {
    if (parsedDates.length < 2) {
        return 'day'
    }
    const diffHours = parsedDates[1].diff(parsedDates[0], 'hour')
    if (diffHours < 1) {
        return 'minute'
    }
    if (diffHours < 24) {
        return 'hour'
    }
    const diffDays = parsedDates[1].diff(parsedDates[0], 'day')
    if (diffDays >= 25) {
        return 'month'
    }
    if (diffDays >= 5) {
        return 'week'
    }
    return 'day'
}

function buildDayStartIndices(parsedDates: Dayjs[]): Set<number> {
    const indices = new Set<number>()
    let prevDateStr = ''
    for (let i = 0; i < parsedDates.length; i++) {
        const dateStr = parsedDates[i].format('YYYY-MM-DD')
        if (dateStr !== prevDateStr) {
            indices.add(i)
            prevDateStr = dateStr
        }
    }
    return indices
}

function buildVisibleBoundaries(parsedDates: Dayjs[]): Set<number> {
    const boundaries: number[] = []
    for (let i = 0; i < parsedDates.length; i++) {
        const prev = i > 0 ? parsedDates[i - 1] : null
        if (!prev || prev.month() !== parsedDates[i].month()) {
            boundaries.push(i)
        }
    }

    const visible = new Set(boundaries)
    const minGap = Math.max(3, Math.floor(parsedDates.length / 10))

    if (boundaries.length >= 2 && boundaries[1] - boundaries[0] < minGap) {
        visible.delete(boundaries[0])
    }
    if (boundaries.length >= 2 && boundaries[boundaries.length - 1] - boundaries[boundaries.length - 2] < minGap) {
        visible.delete(boundaries[boundaries.length - 1])
    }

    return visible
}
