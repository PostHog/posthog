import { type DateTimeRange, type DateTimeValue, CUSTOM_RANGE } from '@posthog/quill'

import { type Dayjs, dayjs } from 'lib/dayjs'

import { RELATIVE_TIME, type TimeRange } from './timeRangeSchema'

/** A preset the picker offers, which runs from `from` to now, such as `{ label: 'Last hour', from: 'now-1h' }`. */
export type QuickRange = {
    label: string
    from: string
}

export const DEFAULT_QUICK_RANGES: QuickRange[] = [
    { label: 'Last 24 hours', from: 'now-24h' },
    { label: 'Last 7 days', from: 'now-7d' },
    { label: 'Last 14 days', from: 'now-14d' },
    { label: 'Last 30 days', from: 'now-30d' },
    { label: 'Last 90 days', from: 'now-90d' },
]

const UNIT_SECONDS: Record<string, number> = { s: 1, m: 60, h: 3600, d: 86_400, w: 604_800 }
const HAS_OFFSET = /(Z|[+-]\d{2}:?\d{2})$/i
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/

/**
 * A point of a saved range as a date, resolved the way the query batch API resolves it: `now-` minus a fixed span,
 * except months and years, which step back on the calendar in `timezone`, and an ISO time without an offset read in
 * `timezone`. Left out, `timezone` is the browser's. The schema rejects any other form.
 */
function resolve(point: string, timezone?: string): Dayjs {
    const match = RELATIVE_TIME.exec(point)
    if (match) {
        const amount = Number(match[1])
        const unit = match[2]
        if (unit === 'M' || unit === 'y') {
            const now = timezone ? dayjs().tz(timezone) : dayjs()
            return now.subtract(amount, unit === 'M' ? 'month' : 'year')
        }
        return dayjs().subtract(amount * UNIT_SECONDS[unit], 'second')
    }
    if (point === 'now') {
        return dayjs()
    }
    return timezone && !HAS_OFFSET.test(point) ? dayjs.tz(point, timezone) : dayjs(point)
}

// The query batch API reads a date `to` through the end of that day, so the range ends at the next midnight.
function resolveEnd(point: string, timezone?: string): Dayjs {
    const end = resolve(point, timezone)
    return DATE_ONLY.test(point) ? end.add(1, 'day') : end
}

/** The presets as quill's picker takes them. Ids start at 1, because 0 is the picker's custom range. */
export function pickerRanges(quick: QuickRange[], timezone?: string): DateTimeRange[] {
    return quick.map(({ label, from }, index) => ({
        id: index + 1,
        name: label,
        rangeSetter: () => resolve(from, timezone).toDate(),
    }))
}

export function toPickerValue(time: TimeRange, quick: QuickRange[], timezone?: string): DateTimeValue {
    const index = time.to === 'now' ? quick.findIndex((range) => range.from === time.from) : -1
    return {
        start: resolve(time.from, timezone).toDate(),
        end: resolveEnd(time.to, timezone).toDate(),
        range: index >= 0 ? pickerRanges(quick, timezone)[index] : CUSTOM_RANGE,
    }
}

export function fromPickerValue(value: DateTimeValue, quick: QuickRange[]): TimeRange {
    const preset = quick[value.range.id - 1]
    return preset && value.range.id !== CUSTOM_RANGE.id
        ? { from: preset.from, to: 'now' }
        : { from: value.start.toISOString(), to: value.end.toISOString() }
}

const UNIT_NAMES: Record<string, string> = {
    s: 'second',
    m: 'minute',
    h: 'hour',
    d: 'day',
    w: 'week',
    M: 'month',
    y: 'year',
}

function isMidnight(time: Dayjs): boolean {
    return time.hour() === 0 && time.minute() === 0 && time.second() === 0
}

export function describeTimeRange(time: TimeRange, quick: QuickRange[], timezone?: string): string {
    const preset = time.to === 'now' ? quick.find((range) => range.from === time.from) : undefined
    if (preset) {
        return preset.label
    }
    const relative = time.to === 'now' ? RELATIVE_TIME.exec(time.from) : null
    if (relative) {
        const amount = Number(relative[1])
        return `Last ${amount} ${UNIT_NAMES[relative[2]]}${amount === 1 ? '' : 's'}`
    }
    const start = resolve(time.from, timezone)
    const end = resolveEnd(time.to, timezone)
    // An end at midnight closes the day before, so a range of whole days names its last day.
    if (isMidnight(start) && isMidnight(end)) {
        const lastDay = end.subtract(1, 'day')
        return lastDay.isSame(start, 'day')
            ? start.format('MMM D')
            : `${start.format('MMM D')} – ${lastDay.format('MMM D')}`
    }
    if (start.isSame(end, 'day')) {
        return `${start.format('MMM D, HH:mm')} – ${end.format('HH:mm')}`
    }
    return `${start.format('MMM D, HH:mm')} – ${end.format('MMM D, HH:mm')}`
}
