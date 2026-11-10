import { type Dayjs, dayjs } from 'lib/dayjs'

import { isEventsNode, isFunnelsQuery } from '~/queries/schema/node-guards'
import type { InsightQueryNode } from '~/queries/schema/schema-general'

export type EmptyStateReason =
    | { kind: 'never-sent'; events: string[] }
    | { kind: 'last-seen-before'; event: string; lastSeen: Dayjs }
    | { kind: 'last-seen-after'; event: string; lastSeen: Dayjs }
    | { kind: 'filtered'; event: string }
    | { kind: 'unknown' }

interface EmptyStateReasonInput {
    /** When each series event was last sent; null for an event the project has never received. */
    lastSeen: Record<string, string | null>
    rangeStart: Dayjs | null
    rangeEnd: Dayjs | null
    hasFilters: boolean
}

export function emptyStateReason({
    lastSeen,
    rangeStart,
    rangeEnd,
    hasFilters,
}: EmptyStateReasonInput): EmptyStateReason {
    const events = Object.keys(lastSeen)
    const seen = events
        .filter((event) => lastSeen[event])
        .map((event) => ({ event, lastSeen: dayjs(lastSeen[event]) }))
        .sort((a, b) => b.lastSeen.valueOf() - a.lastSeen.valueOf())

    if (events.length === 0) {
        return { kind: 'unknown' }
    }
    if (seen.length === 0) {
        return { kind: 'never-sent', events }
    }
    const latest = seen[0]
    if (rangeStart && latest.lastSeen.isBefore(rangeStart)) {
        return { kind: 'last-seen-before', ...latest }
    }
    if (rangeEnd && latest.lastSeen.isAfter(rangeEnd)) {
        return { kind: 'last-seen-after', ...latest }
    }
    // Last sent inside the range, so the events exist there and a filter is the likely cause.
    return hasFilters ? { kind: 'filtered', event: latest.event } : { kind: 'unknown' }
}

/**
 * The events whose last-sent time can explain an empty result, or null when a series is not a plain event.
 * A funnel is empty when nobody did its first step, so only that step counts.
 */
export function explainableEvents(querySource: InsightQueryNode | null): string[] | null {
    const series = querySource && 'series' in querySource ? querySource.series : null
    const counted = series && isFunnelsQuery(querySource) ? series.slice(0, 1) : series
    const events = counted?.map((node) => (isEventsNode(node) ? node.event : null)) ?? []
    if (!events.length || !events.every((event): event is string => !!event)) {
        return null
    }
    return [...new Set(events)]
}

function isPropertyGroup(value: unknown): value is { values: unknown[] } {
    const group = value as { type?: unknown; values?: unknown } | null
    return !!group && (group.type === 'AND' || group.type === 'OR') && Array.isArray(group.values)
}

/** Whether a query's `properties`, a flat list or nested AND/OR groups, holds at least one filter. */
export function hasPropertyFilters(properties: unknown): boolean {
    if (Array.isArray(properties)) {
        return properties.some((item) => !isPropertyGroup(item) || hasPropertyFilters(item.values))
    }
    return isPropertyGroup(properties) && hasPropertyFilters(properties.values)
}

const RELATIVE_RANGE_DAYS = [7, 14, 30, 90, 180, 365]

/** The shortest familiar relative range that reaches a week before `lastSeen`, else an absolute start date. */
export function rangeReaching(lastSeen: Dayjs, now: Dayjs = dayjs()): { dateFrom: string; label: string } {
    const daysNeeded = now.diff(lastSeen, 'day') + 7
    const days = RELATIVE_RANGE_DAYS.find((option) => option >= daysNeeded)
    if (days) {
        return { dateFrom: `-${days}d`, label: `Show last ${days} days` }
    }
    const start = lastSeen.subtract(7, 'day')
    return { dateFrom: start.format('YYYY-MM-DD'), label: `Show from ${start.format('D MMM YYYY')}` }
}
