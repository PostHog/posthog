import { CUSTOM_RANGE, type DateTimeValue, quickRanges } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

const UNIT_MS: Record<string, number> = { s: 1e3, m: 6e4, h: 36e5, d: 864e5, w: 6048e5 }

const QUICK_RANGE_FROM: Record<string, string> = {
    'Last 5 minutes': 'now-5m',
    'Last 15 minutes': 'now-15m',
    'Last 30 minutes': 'now-30m',
    'Last 1 hour': 'now-1h',
    'Last 3 hours': 'now-3h',
    'Last 6 hours': 'now-6h',
    'Last 12 hours': 'now-12h',
    'Last 24 hours': 'now-24h',
    'Last 2 days': 'now-2d',
    'Last 7 days': 'now-7d',
    'Last 30 days': 'now-30d',
    'Last 90 days': 'now-90d',
    'Last 6 months': 'now-6M',
    'Last 1 year': 'now-1y',
    'Last 2 years': 'now-2y',
}

function roundToUnit(date: Date, unit: string, up: boolean): void {
    if (unit === 'y') {
        date.setUTCMonth(0, 1)
    }
    if (unit === 'M') {
        date.setUTCDate(1)
    }
    if (unit === 'w') {
        date.setUTCDate(date.getUTCDate() - ((date.getUTCDay() + 6) % 7))
    }
    if ('yMwd'.includes(unit)) {
        date.setUTCHours(0, 0, 0, 0)
    } else {
        date.setTime(Math.floor(date.getTime() / UNIT_MS[unit]) * UNIT_MS[unit])
    }
    if (!up) {
        return
    }
    if (unit === 'y' || unit === 'M') {
        date.setUTCMonth(date.getUTCMonth() + (unit === 'y' ? 12 : 1))
    } else {
        date.setTime(date.getTime() + UNIT_MS[unit])
    }
    date.setTime(date.getTime() - 1)
}

// With roundUp a "/d" step resolves to the end of the day, so that "now/d" as the end of a range covers all of today.
export function parseTimeExpression(expression: string, now: Date, roundUp = false): Date | null {
    const text = expression.trim()
    if (text === 'now') {
        return new Date(now)
    }
    const relative = /^now((?:[-+]\d+[smhdwMy]|\/[smhdwMy])+)$/.exec(text)
    if (relative) {
        const date = new Date(now)
        for (const [, sign, amount, unit, roundUnit] of relative[1].matchAll(/([-+])(\d+)([smhdwMy])|\/([smhdwMy])/g)) {
            if (roundUnit) {
                roundToUnit(date, roundUnit, roundUp)
                continue
            }
            const step = (sign === '-' ? -1 : 1) * Number(amount)
            if (unit === 'M' || unit === 'y') {
                date.setUTCMonth(date.getUTCMonth() + step * (unit === 'y' ? 12 : 1))
            } else {
                date.setTime(date.getTime() + step * UNIT_MS[unit])
            }
        }
        return date
    }
    const epoch = /^(\d{10,13})(\.\d+)?$/.exec(text)
    if (epoch) {
        return new Date(Math.round(Number(text) * (epoch[1].length === 10 ? 1000 : 1)))
    }
    const date = new Date(text)
    return isNaN(date.getTime()) ? null : date
}

export function isRelativeTimeRange(from: string, to: string): boolean {
    return from.trim().startsWith('now') || to.trim().startsWith('now')
}

function quickRangeFor(from: string, to: string): (typeof quickRanges)[number] | undefined {
    if (to.trim() !== 'now') {
        return undefined
    }
    return quickRanges.find((range) => QUICK_RANGE_FROM[range.name] === from.trim())
}

export function timeRangeToPickerValue(from: string, to: string, now: Date): DateTimeValue {
    const range = quickRangeFor(from, to)
    if (range) {
        return { start: range.rangeSetter(now), end: now, range }
    }
    return {
        start: parseTimeExpression(from, now) ?? dayjs(now).subtract(6, 'hour').toDate(),
        end: parseTimeExpression(to, now, true) ?? now,
        range: CUSTOM_RANGE,
    }
}

export function pickerValueToTimeRange(value: DateTimeValue): { from: string; to: string } {
    const from = value.range.id !== CUSTOM_RANGE.id ? QUICK_RANGE_FROM[value.range.name] : undefined
    if (from) {
        return { from, to: 'now' }
    }
    return { from: value.start.toISOString(), to: value.end.toISOString() }
}

export function timeRangeLabel(from: string, to: string, now: Date): string {
    const range = quickRangeFor(from, to)
    if (range) {
        return range.name
    }
    if (isRelativeTimeRange(from, to)) {
        return `${from.trim()} to ${to.trim()}`
    }
    const start = parseTimeExpression(from, now)
    const end = parseTimeExpression(to, now, true)
    if (!start || !end) {
        return `${from} to ${to}`
    }
    return `${dayjs(start).format('MMM D, HH:mm')} to ${dayjs(end).format('MMM D, HH:mm')}`
}
