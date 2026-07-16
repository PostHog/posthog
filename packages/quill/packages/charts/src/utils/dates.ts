import { type Dayjs, parseDateInTimezone } from './dayjs'

/** Bucket size for a date-based X axis. Mirrors `IntervalType` from product code without
 * coupling hog-charts to it. */
export type TimeInterval = 'second' | 'minute' | 'hour' | 'day' | 'week' | 'month' | 'quarter' | 'year'

interface CreateXAxisTickCallbackArgs {
    interval?: TimeInterval
    allDays: (string | number)[]
    timezone: string
}

type TickMode =
    | { type: 'month' }
    | { type: 'quarter' }
    | { type: 'year' }
    | { type: 'day' }
    | { type: 'monthly'; visibleBoundaries: Set<number> }
    | { type: 'hourly' }
    | { type: 'hourly-multi-day'; step: number; dayStartIndices: Set<number> }

export function createXAxisTickCallback({
    interval,
    allDays,
    timezone,
}: CreateXAxisTickCallbackArgs): ((value: string | number, index: number) => string | null) | undefined {
    if (allDays.length === 0 || typeof allDays[0] !== 'string') {
        return
    }

    const parsedDates = allDays.map((d) => parseDateForAxis(String(d), timezone))
    const first = parsedDates[0]
    const last = parsedDates[parsedDates.length - 1]

    if (!first?.isValid() || !last?.isValid()) {
        return
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

export const parseDateForAxis = parseDateInTimezone

/** Full date label for a tooltip header. Unlike the sparse, abbreviated axis ticks, every point
 *  gets a complete, unambiguous label, with the weekday when the bucket names a single day
 *  ("Sat, Jun 6, 2026", "Sat, Jun 6, 14:00" — but week/month buckets span days, so no weekday).
 *  Non-date labels pass through unchanged. */
export function createTooltipDateFormatter({
    interval,
    timezone,
}: {
    interval: TimeInterval
    timezone: string
}): (label: string) => string {
    return (label: string): string => {
        const date = parseDateInTimezone(label, timezone)
        if (!date.isValid()) {
            return label
        }
        switch (interval) {
            case 'second':
                return date.format('ddd, MMM D, HH:mm:ss')
            case 'minute':
            case 'hour':
                return date.format('ddd, MMM D, HH:mm')
            case 'month':
                return date.format('MMM YYYY')
            case 'week':
                return date.format('MMM D, YYYY')
            case 'day':
            default:
                return date.format('ddd, MMM D, YYYY')
        }
    }
}

function pickMode(interval: TimeInterval, parsedDates: Dayjs[], first: Dayjs, last: Dayjs): TickMode {
    const spanMonths = (last.year() - first.year()) * 12 + last.month() - first.month()
    const spanDays = last.diff(first, 'day')

    if (interval === 'quarter') {
        return { type: 'quarter' }
    }
    if (interval === 'year') {
        return { type: 'year' }
    }
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
        case 'quarter':
            return formatQuarterLabel(date)
        case 'year':
            return String(date.year())
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

// Mirrors formatMonthLabel's convention: the year marks the year boundary, "Q2".."Q4" otherwise.
function formatQuarterLabel(date: Dayjs): string {
    if (date.month() === 0) {
        return String(date.year())
    }
    return `Q${Math.floor(date.month() / 3) + 1}`
}

function inferInterval(parsedDates: Dayjs[]): TimeInterval {
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
    if (diffDays >= 300) {
        return 'year'
    }
    if (diffDays >= 80) {
        return 'quarter'
    }
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
