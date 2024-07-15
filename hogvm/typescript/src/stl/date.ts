import { DateTime } from 'luxon'

export interface HogDate {
    __hogDate__: true
    year: number
    month: number
    day: number
}

export interface HogDateTime {
    __hogDateTime__: true
    /** Timestamp float in seconds */
    dt: number
    zone: string
}

export function isHogDate(obj: any): obj is HogDate {
    return obj && obj.__hogDate__ && 'year' in obj && 'month' in obj && 'day' in obj
}

export function isHogDateTime(obj: any): obj is HogDateTime {
    return obj && obj.__hogDateTime__ && 'dt' in obj && 'zone' in obj
}

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
            dt: dateTime.toMillis() / 1000,
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
    return toHogDateTime(Date.now(), zone)
}

export function toUnixTimestamp(input: HogDateTime | HogDate | string, zone?: string): number {
    if (isHogDateTime(input)) {
        return input.dt
    }
    if (isHogDate(input)) {
        return toHogDateTime(input).dt
    }
    return DateTime.fromISO(input, { zone: zone || 'UTC' }).toMillis() / 1000
}

export function fromUnixTimestamp(input: number): HogDateTime {
    return toHogDateTime(input)
}

export function toTimeZone(input: HogDateTime, zone: string): HogDateTime | HogDate {
    if (!isHogDateTime(input)) {
        throw new Error('Expected a DateTime')
    }
    return { ...input, zone }
}

export function toDate(input: string): HogDate {
    const dt = DateTime.fromISO(input)
    return {
        __hogDate__: true,
        year: dt.year,
        month: dt.month,
        day: dt.day,
    }
}

export function toDateTime(input: string, zone?: string): HogDateTime {
    const dt = DateTime.fromISO(input, { zone: zone || 'UTC' })
    return {
        __hogDateTime__: true,
        dt: dt.toMillis() / 1000,
        zone: zone || 'UTC',
    }
}
