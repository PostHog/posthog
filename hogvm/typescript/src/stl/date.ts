export interface HogTimestamp {
    __hogTimestamp__: true
    ts: number
    zone: string
}
export interface HogDate {
    __hogDate__: true
    year: number
    month: number
    day: number
    hour: number
    zone: string
}
export interface HogDateTime {
    __hogDateTime__: true
    year: number
    month: number
    day: number
    hour: number
    minute: number
    second: number
    millisecond: number
    zone: string
}

export function isHogTimestamp(obj: any): obj is HogTimestamp {
    return obj && obj.__hogTimestamp__ && 'ts' in obj && 'zone' in obj
}

export function isHogDate(obj: any): obj is HogDate {
    return obj && obj.__hogDate__ && 'ts' in obj && 'zone' in obj
}

export function isHogDateTime(obj: any): obj is HogDateTime {
    return obj && obj.__hogDateTime__ && 'ts' in obj && 'zone' in obj
}

export function toHogTimestamp(ts: number, zone?: string): HogTimestamp {
    return {
        __hogTimestamp__: true,
        ts: ts,
        zone: zone || 'UTC',
    }
}

export function toHogDate(year: number, month: number, day: number, zone?: string): HogDate {
    return {
        __hogDate__: true,
        year: year,
        month: month,
        day: day,
        hour: 0,
        zone: zone || 'UTC',
    }
}

export function toHogDateTime(
    year: number,
    month: number,
    day: number,
    hour: number,
    minute: number,
    second: number,
    millisecond: number,
    zone?: string
): HogDateTime {
    return {
        __hogDateTime__: true,
        year: year,
        month: month,
        day: day,
        hour: hour,
        minute: minute,
        second: second,
        millisecond: millisecond,
        zone: zone || 'UTC',
    }
}

// EXPORTED STL functions

export function now(zone?: string): HogTimestamp {
    return toHogTimestamp(Date.now(), zone)
}

export function toUnixTimestamp(input: HogTimestamp | HogDateTime | HogDate | string, zone?: string): number {
    if (typeof input !== 'string' && zone) {
        throw new Error('zone is only supported for string input')
    }
    if (isHogTimestamp(input)) {
        return input.ts
    }
}

export function fromUnixTimestamp(input: number): HogTimestamp {
    return toHogTimestamp(input)
}

export function toTimeZone(
    input: HogTimestamp | HogDateTime | HogDate,
    zone: string
): HogTimestamp | HogDateTime | HogDate {
    return {
        ...input,
        zone: zone,
    }
}
