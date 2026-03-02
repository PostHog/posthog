import { Dayjs } from 'lib/dayjs'
import { dayjsUtcToTimezone } from 'lib/dayjs'

import { IntervalType } from '~/types'

interface CreateXAxisTickCallbackArgs {
    interval?: IntervalType
    allDays: string[]
    timezone: string
}

type TickMode =
    | { type: 'month' }
    | { type: 'day' }
    | { type: 'monthly'; visibleBoundaries: Set<number> }
    | { type: 'hourly' }
    | { type: 'hourly-multi-day'; step: number }

export function createXAxisTickCallback({
    interval,
    allDays,
    timezone,
}: CreateXAxisTickCallbackArgs): (value: string | number, index: number) => string | null {
    if (allDays.length === 0) {
        return (value) => String(value)
    }

    const parsedDates = allDays.map((d) => dayjsUtcToTimezone(d, timezone, false))
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
        return { type: 'hourly-multi-day', step }
    }
    return { type: 'hourly' }
}

function isTickVisible(mode: TickMode, date: Dayjs, index: number): boolean {
    switch (mode.type) {
        case 'monthly':
            return mode.visibleBoundaries.has(index)
        case 'hourly-multi-day':
            return index === 0 || date.hour() % mode.step === 0
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
            return date.hour() === 0 || index === 0 ? date.format('MMM D') : date.format('HH:mm')
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
