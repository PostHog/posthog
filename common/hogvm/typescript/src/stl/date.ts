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
    return (parseDateLike(input, zone) ?? INVALID).toSeconds()
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

/**
 * The shared "date-like string" grammar, implemented identically by all three HogVMs. The canonical
 * copy of the spec lives above `parse_datetime_to_seconds` in `rust/common/hogvm/src/stl.rs`;
 * `common/hogvm/python/stl/date.py` (`_parse_date_like`) is the third. Change all three together.
 *
 *     input := WS* date ( SEP time zone? )? WS*
 *     date  := YYYY "-" MM "-" DD              # extended format only, YYYY >= 0001
 *     SEP   := "T" | "t" | " "
 *     time  := HH ":" MM ( ":" SS frac? )?     # HH <= 23; a fraction requires seconds
 *     frac  := ("." | ",") DIGIT{1,9}          # truncated to milliseconds
 *     zone  := "Z" | "z" | ("+"|"-") HH ( ":"? MM )?   # offset HH <= 23, MM <= 59
 *
 * Luxon's `fromISO` is both too permissive and too strict for this. Too permissive: it accepts
 * `2024`, `2024-01`, `20240101`, `2024-W05`, `2024-001`, and a time-only `12:30` that silently
 * resolves to *today's* date — all plausible values of an ordinary string property, and this
 * coercion is implicit, so a false positive changes the meaning of a comparison the filter author
 * never marked as a date comparison. Too strict: it rejects `2024-01-01 00:00:00`, the canonical
 * ClickHouse form that HogQL emits and that Python and Rust both accept — so `toDateTime` on it
 * returned `{dt: NaN}`. Validating against the grammar first fixes both directions.
 */
// [0-9] to stay byte-for-byte parallel with the Rust and Python patterns, where \d is
// Unicode-aware and had to be banned (JS's \d is already ASCII-only).
const DATE_LIKE =
    /^([0-9]{4})(-[0-9]{2}-[0-9]{2})(?:[Tt ]((?:[01][0-9]|2[0-3]):[0-5][0-9])(?::([0-5][0-9])(?:[.,]([0-9]{1,9}))?)?(Z|z|[+-](?:[01][0-9]|2[0-3])(?::?[0-5][0-9])?)?)?$/

/** Luxon `DateTime` for a string matching the shared grammar, else null. `zone` applies only to input carrying no zone of its own. */
export function parseDateLike(input: string, zone?: string): DateTime | null {
    // Callers reach here with whatever an event property held — `toUnixTimestamp(event.properties.x)`
    // passes its argument through unchecked — so a non-string must return null, not throw on `.trim`.
    if (typeof input !== 'string') {
        return null
    }
    const match = DATE_LIKE.exec(input.trim())
    if (!match) {
        return null
    }
    const [, year, monthDay, hourMinute, second, fraction, offset] = match
    // Year 0 is valid to luxon and chrono but not to Python's `datetime`; excluded so the three
    // accept-sets stay identical.
    if (year === '0000') {
        return null
    }
    // Sub-millisecond digits are truncated, not rounded, to match luxon's own precision and Rust's
    // `timestamp_millis`. Keeping microseconds (as Python's `datetime` does) surfaced as a
    // `result_mismatch` against the Node baseline.
    const millis = fraction ? `.${fraction.slice(0, 3).padEnd(3, '0')}` : ''
    // Normalize to strict ISO so luxon's parser accepts it: `T` separator, uppercase `Z`.
    const time = hourMinute ? `T${hourMinute}${second ? `:${second}${millis}` : ''}${offset?.toUpperCase() ?? ''}` : ''
    const dt = DateTime.fromISO(`${year}${monthDay}${time}`, { zone: zone || 'UTC' })
    return dt.isValid ? dt : null
}

// NOTE: unparseable input keeps each VM's *existing* failure mode — here an invalid luxon DateTime
// (so `.year`/`.toSeconds()` are NaN, as before), while Python raises and Rust errors into a null.
// Converging those three is a separate change; this only converges *what parses*.
const INVALID = DateTime.invalid('not a date-like string')

export function toDate(input: string | number): HogDate {
    // Previously `DateTime.fromISO(input)` with no zone, i.e. the *system* zone — same class of
    // host-dependent bug as Python's, and a day off from `toDateTime` for offsets west of UTC.
    const dt = typeof input === 'number' ? DateTime.fromSeconds(input) : (parseDateLike(input) ?? INVALID)
    return {
        __hogDate__: true,
        year: dt.year,
        month: dt.month,
        day: dt.day,
    }
}

export function toDateTime(input: string | number, zone?: string): HogDateTime {
    const dt = typeof input === 'number' ? input : (parseDateLike(input, zone) ?? INVALID).toSeconds()
    return {
        __hogDateTime__: true,
        dt: dt,
        zone: zone || 'UTC',
    }
}

/** Epoch seconds for a date-like string, parsed the same way `toDateTime` would, else null. */
export function dateStringToSeconds(input: string): number | null {
    return parseDateLike(input)?.toSeconds() ?? null
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
