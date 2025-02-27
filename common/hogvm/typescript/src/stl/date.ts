import { DateTime } from 'luxon'

import { isHogDate, isHogDateTime } from '../objects'
import { HogDate, HogDateTime } from '../types'

export function toHogDate(year: number, month: number, day: number): HogDate {
    return {
        __hogDate__: true,
        year: year,
        month: month,
        day: day,
    }
}

export function toHogDateTime(timestamp: number | HogDate, zone?: string): HogDateTime {
    if (isHogDate(timestamp)) {
        const dateTime = DateTime.fromObject(
            {
                year: timestamp.year,
                month: timestamp.month,
                day: timestamp.day,
            },
            { zone: zone || 'UTC' }
        )
        return {
            __hogDateTime__: true,
            dt: dateTime.toSeconds(),
            zone: dateTime.zoneName || 'UTC',
        }
    }
    return {
        __hogDateTime__: true,
        dt: timestamp,
        zone: zone || 'UTC',
    }
}

// EXPORTED STL functions

export function now(zone?: string): HogDateTime {
    return toHogDateTime(Date.now() / 1000, zone)
}

export function toUnixTimestamp(input: HogDateTime | HogDate | string, zone?: string): number {
    if (isHogDateTime(input)) {
        return input.dt
    }
    if (isHogDate(input)) {
        return toHogDateTime(input).dt
    }
    return DateTime.fromISO(input, { zone: zone || 'UTC' }).toSeconds()
}

export function fromUnixTimestamp(input: number): HogDateTime {
    return toHogDateTime(input)
}

export function toUnixTimestampMilli(input: HogDateTime | HogDate | string, zone?: string): number {
    return toUnixTimestamp(input, zone) * 1000
}

export function fromUnixTimestampMilli(input: number): HogDateTime {
    return toHogDateTime(input / 1000)
}

export function toTimeZone(input: HogDateTime, zone: string): HogDateTime | HogDate {
    if (!isHogDateTime(input)) {
        throw new Error('Expected a DateTime')
    }
    return { ...input, zone }
}

export function toDate(input: string | number): HogDate {
    const dt = typeof input === 'number' ? DateTime.fromSeconds(input) : DateTime.fromISO(input)
    return {
        __hogDate__: true,
        year: dt.year,
        month: dt.month,
        day: dt.day,
    }
}

export function toDateTime(input: string | number, zone?: string): HogDateTime {
    const dt = typeof input === 'number' ? input : DateTime.fromISO(input, { zone: zone || 'UTC' }).toSeconds()
    return {
        __hogDateTime__: true,
        dt: dt,
        zone: zone || 'UTC',
    }
}

/** Convert from ClickHouse format string to Luxon format string */
const tokenTranslations: Record<string, string> = {
    a: 'EEE',
    b: 'MMM',
    c: 'MM',
    C: 'yy',
    d: 'dd',
    D: 'MM/dd/yy',
    e: 'd',
    f: 'SSS',
    F: 'yyyy-MM-dd',
    g: 'yy',
    G: 'yyyy',
    h: 'hh',
    H: 'HH',
    i: 'mm',
    I: 'hh',
    j: 'ooo',
    k: 'HH',
    l: 'hh',
    m: 'MM',
    M: 'MMMM',
    n: '\n',
    p: 'a',
    Q: 'q',
    r: 'hh:mm a',
    R: 'HH:mm',
    s: 'ss',
    S: 'ss',
    t: '\t',
    T: 'HH:mm:ss',
    u: 'E',
    V: 'WW',
    w: 'E',
    W: 'EEEE',
    y: 'yy',
    Y: 'yyyy',
    z: 'ZZZ',
    '%': '%',
}
export function formatDateTime(input: any, format: string, zone?: string): string {
    if (!isHogDateTime(input)) {
        throw new Error('Expected a DateTime')
    }
    if (!format) {
        throw new Error('formatDateTime requires at least 2 arguments')
    }
    let formatString = ''
    let acc = ''
    for (let i = 0; i < format.length; i++) {
        if (format[i] === '%') {
            if (acc.length > 0) {
                formatString += `'${acc}'`
                acc = ''
            }
            i += 1
            if (i < format.length && tokenTranslations[format[i]]) {
                formatString += tokenTranslations[format[i]]
            }
        } else {
            acc += format[i]
        }
    }
    if (acc.length > 0) {
        formatString += `'${acc}'`
    }
    return DateTime.fromSeconds(input.dt, { zone: zone || input.zone }).toFormat(formatString)
}
