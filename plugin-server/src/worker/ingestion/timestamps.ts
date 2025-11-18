import { DateTime } from 'luxon'

import { PluginEvent } from '@posthog/plugin-scaffold'

type IngestionWarningCallback = (type: string, details: Record<string, any>) => void

/**
 * Parse event timestamp from plugin-server event data.
 *
 * NOTE: Timestamp normalization (clock skew adjustment, future event clamping, offset handling)
 * is now handled in the Rust capture service. This function only parses the timestamp string
 * that comes from the event data. The timestamp in event data is already normalized by the Rust
 * capture service (via parse_event_timestamp in rust/common/types/src/timestamp.rs).
 *
 * The Rust capture service handles:
 * - Clock skew adjustment using sent_at and now
 * - Future event clamping (to now if >23 hours in future)
 * - Out-of-bounds validation (year < 0 or > 9999, fallback to epoch)
 * - Offset handling
 *
 * This function only needs to parse the string to a DateTime object.
 */
export function parseEventTimestamp(data: PluginEvent, callback?: IngestionWarningCallback): DateTime {
    // The timestamp has already been normalized by the Rust capture service
    // Just parse it from the data
    if (data['timestamp']) {
        const parsedTs = parseDate(data['timestamp'])

        if (!parsedTs.isValid) {
            callback?.('ignored_invalid_timestamp', {
                eventUuid: data['uuid'] ?? '',
                field: 'timestamp',
                value: data['timestamp'],
                reason: parsedTs.invalidExplanation || 'unknown error',
            })
            return DateTime.utc()
        }

        const parsedTsOutOfBounds = parsedTs.year < 0 || parsedTs.year > 9999
        if (parsedTsOutOfBounds) {
            callback?.('ignored_invalid_timestamp', {
                eventUuid: data['uuid'] ?? '',
                field: 'timestamp',
                value: data['timestamp'],
                reason: 'out of bounds',
                parsed_year: parsedTs.year,
            })
            return DateTime.utc()
        }

        return parsedTs
    }

    // Fallback to current time if no timestamp provided
    return DateTime.utc()
}

export function parseDate(supposedIsoString: string): DateTime {
    const jsDate = new Date(supposedIsoString)
    if (Number.isNaN(jsDate.getTime())) {
        return DateTime.fromISO(supposedIsoString).toUTC()
    }
    return DateTime.fromJSDate(jsDate).toUTC()
}

export function toYearMonthDayInTimezone(
    timestamp: number,
    timeZone: string
): { year: number; month: number; day: number } {
    const parts = new Intl.DateTimeFormat('en', {
        timeZone,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
    }).formatToParts(new Date(timestamp))
    const year = parts.find((part) => part.type === 'year')?.value
    const month = parts.find((part) => part.type === 'month')?.value
    const day = parts.find((part) => part.type === 'day')?.value
    if (!year || !month || !day) {
        throw new Error('Failed to get year, month, or day')
    }
    return { year: Number(year), month: Number(month), day: Number(day) }
}

export function toStartOfDayInTimezone(timestamp: number, timeZone: string): Date {
    const { year, month, day } = toYearMonthDayInTimezone(timestamp, timeZone)
    return DateTime.fromObject(
        { year, month, day, hour: 0, minute: 0, second: 0, millisecond: 0 },
        { zone: timeZone }
    ).toJSDate()
}
