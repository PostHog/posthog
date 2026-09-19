import { formatEventName } from 'scenes/insights/utils'

// Matches the events table: only a column literally named `event` is known to hold event names.
const EVENT_COLUMN_NAME = 'event'

/** Swap a raw PostHog event key (`$pageview`) for its display name (`Pageview`) in chart labels. */
export function humanizeEventColumnValue<T>(columnName: string, value: T): T {
    if (columnName !== EVENT_COLUMN_NAME || typeof value !== 'string') {
        return value
    }
    return (formatEventName(value) ?? value) as T
}
