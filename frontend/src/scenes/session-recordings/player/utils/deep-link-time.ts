import { dayjs } from 'lib/dayjs'

export interface DeepLinkTime {
    // 'timestamp' is an absolute point in the recording (unix ms).
    // 'offset' is a distance from the start of the recording (ms).
    kind: 'timestamp' | 'offset'
    valueMs: number
}

// A replay deep link carries the start position in either `timestamp` or `t`.
// `timestamp` is always absolute. `t` is documented as a seconds offset, but our own
// Slack destination docs emit an ISO date in `t`, so `t` must accept a date too.
// Params arrive as strings or, when they look numeric, as numbers (kea-router coerces them).
// Returns null when a param is present but unparseable, so the caller can surface it.
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

function parseDate(value: string | number): number | null {
    const parsed = dayjs(value)
    return parsed.isValid() ? parsed.valueOf() : null
}
