import { dayjs } from 'lib/dayjs'
import { zeroPad } from 'lib/utils/numbers'

import { TimeUnitType } from '~/types'

export const humanFriendlyMilliseconds = (timestamp: number | undefined): string | undefined => {
    if (typeof timestamp !== 'number') {
        return undefined
    }

    if (timestamp < 1000) {
        return `${Math.ceil(timestamp)}ms`
    }

    return `${(timestamp / 1000).toFixed(2)}s`
}

export function humanFriendlyDuration(
    d: string | number | null | undefined,
    {
        maxUnits,
        secondsPrecision,
        secondsFixed,
    }: { maxUnits?: number; secondsPrecision?: number; secondsFixed?: number } = {}
): string {
    // Convert `d` (seconds) to a human-readable duration string.
    // Example: `1d 10hrs 9mins 8s`
    if (d === '' || d === null || d === undefined || maxUnits === 0) {
        return ''
    }
    d = Number(d)
    if (d < 0) {
        return `-${humanFriendlyDuration(-d)}`
    }
    if (d === 0) {
        return `0s`
    }
    if (d < 1) {
        return `${Math.round(d * 1000)}ms`
    }
    if (d < 60) {
        if (secondsPrecision != null) {
            return `${parseFloat(d.toPrecision(secondsPrecision))}s` // round to s.f. then throw away trailing zeroes
        }
        return `${parseFloat(d.toFixed(secondsFixed ?? 0))}s` // round to fixed point then throw away trailing zeroes
    }

    const days = Math.floor(d / 86400)
    const h = Math.floor((d % 86400) / 3600)
    const m = Math.floor((d % 3600) / 60)
    const s = Math.floor((d % 3600) % 60)

    const dayDisplay = days > 0 ? days + 'd' : ''
    const hDisplay = h > 0 ? h + 'h' : ''
    const mDisplay = m > 0 ? m + 'm' : ''
    const sDisplay = s > 0 ? s + 's' : hDisplay || mDisplay ? '' : '0s'

    let units: string[] = []
    if (days > 0) {
        units = [dayDisplay, hDisplay].filter(Boolean)
    } else {
        units = [hDisplay, mDisplay, sDisplay].filter(Boolean)
    }
    return units.slice(0, maxUnits ?? undefined).join(' ')
}

export function humanFriendlyDiff(from: dayjs.Dayjs | string, to: dayjs.Dayjs | string): string {
    const diff = dayjs(to).diff(dayjs(from), 'seconds')
    return humanFriendlyDuration(diff)
}

export function colonDelimitedDuration(d: string | number | null | undefined, fixedUnits: number | null = 3): string {
    // Convert `d` (seconds) to a colon delimited duration. includes `numUnits` no. of units starting from right
    // Example: `01:10:09:08 = 1d 10hrs 9mins 8s`
    if (d === '' || d === null || d === undefined) {
        return ''
    }
    d = Number(d)

    let s = d
    let weeks = 0,
        days = 0,
        h = 0,
        m = 0

    weeks = !fixedUnits || fixedUnits > 4 ? Math.floor(s / 604800) : 0
    s -= weeks * 604800

    days = !fixedUnits || fixedUnits > 3 ? Math.floor(s / 86400) : 0
    s -= days * 86400

    h = !fixedUnits || fixedUnits > 2 ? Math.floor(s / 3600) : 0
    s -= h * 3600

    m = !fixedUnits || fixedUnits > 1 ? Math.floor(s / 60) : 0
    s -= m * 60

    s = Math.floor(s)

    let stopTrimming = false
    const units: string[] = []

    ;[weeks, days, h, m, s].forEach((unit, i) => {
        if (!fixedUnits && !unit && !stopTrimming && i < 3) {
            return
        }
        units.push(zeroPad(unit, 2))
        stopTrimming = true
    })

    if (fixedUnits) {
        return units.slice(-fixedUnits).join(':')
    }

    return units.join(':')
}

export function reverseColonDelimitedDuration(duration?: string | null): number | null {
    if (!duration) {
        return null
    }

    if (!/^(\d\d?:)*(\d\d?)$/.test(duration)) {
        return null
    }

    let seconds = 0
    const units = duration
        .split(':')
        .map((unit) => Number(unit))
        .reverse()

    ;[1, 60, 3600, 86400, 604800].forEach((unit, index) => {
        if (units[index]) {
            seconds += units[index] * unit
        }
    })

    return seconds
}

export function floorMsToClosestSecond(ms: number): number {
    return Math.floor(ms / 1000) * 1000
}

export function ceilMsToClosestSecond(ms: number): number {
    return Math.ceil(ms / 1000) * 1000
}

export function calculateDays(timeValue: number, timeUnit: TimeUnitType): number {
    if (timeUnit === TimeUnitType.Year) {
        return timeValue * 365
    }
    if (timeUnit === TimeUnitType.Month) {
        return timeValue * 30
    }
    if (timeUnit === TimeUnitType.Week) {
        return timeValue * 7
    }
    return timeValue
}
