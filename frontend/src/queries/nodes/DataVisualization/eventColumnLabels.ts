import { formatEventName } from 'lib/insights/entityFilterNames'

// Matches the events table: only a column literally named `event` is known to hold event names.
const EVENT_COLUMN_NAME = 'event'

/** Swap a raw PostHog event key (`$pageview`) for its display name (`Pageview`) in chart labels. */
export function humanizeEventColumnValue<T>(columnName: string, value: T): T {
    if (columnName !== EVENT_COLUMN_NAME || typeof value !== 'string') {
        return value
    }
    return (formatEventName(value) ?? value) as T
}

export function chartAxisValues<T>(column: string, values: T[], useRawLabels: boolean): { data: T[]; rawData?: T[] } {
    if (useRawLabels || column !== EVENT_COLUMN_NAME) {
        return { data: values }
    }
    const labels = values.map((value) => humanizeEventColumnValue(column, value))
    return labels.some((label, index) => label !== values[index]) ? { data: labels, rawData: values } : { data: values }
}
