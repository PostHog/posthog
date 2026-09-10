import { dayjs } from 'lib/dayjs'

export interface DeepLinkTime {
    // 'timestamp' is an absolute point in the recording (unix ms).
    // 'offset' is a distance from the start of the recording (ms).
    kind: 'timestamp' | 'offset'
    valueMs: number
}

// `timestamp` is absolute (unix ms or ISO date). `t` is a seconds offset, but the CDP destination
// docs emit an ISO date in `t`, so `t` accepts a date too. kea-router coerces numeric params to numbers.
// Returns null when a param is present but unparseable.
export function parseDeepLinkTime(
    timestampParam: string | number | undefined,
    tParam: string | number | undefined
): DeepLinkTime | null {
    if (timestampParam) {
        const absolute = parseAbsoluteMs(timestampParam)
        if (absolute !== null) {
            return { kind: 'timestamp', valueMs: absolute }
        }
    }
    if (tParam) {
        const seconds = toFiniteNumber(tParam)
        if (seconds !== null) {
            return { kind: 'offset', valueMs: seconds * 1000 }
        }
        const absolute = parseDate(tParam)
        if (absolute !== null) {
            return { kind: 'timestamp', valueMs: absolute }
        }
    }
    return null
}

function parseAbsoluteMs(value: string | number): number | null {
    // A bare number is a unix-ms timestamp; anything else must be a parseable date.
    return toFiniteNumber(value) ?? parseDate(value)
}

function toFiniteNumber(value: string | number): number | null {
    if (typeof value === 'string' && value.trim() === '') {
        return null
    }
    const asNumber = Number(value)
    return Number.isFinite(asNumber) ? asNumber : null
}

// Zone-less and partial dates parse in the viewer's local zone, so the same link would land on
// different frames for different viewers. Require a full ISO datetime with an explicit zone.
const ISO_DATETIME_WITH_ZONE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$/

function parseDate(value: string | number): number | null {
    if (typeof value !== 'string' || !ISO_DATETIME_WITH_ZONE.test(value)) {
        return null
    }
    const parsed = dayjs(value)
    return parsed.isValid() ? parsed.valueOf() : null
}
