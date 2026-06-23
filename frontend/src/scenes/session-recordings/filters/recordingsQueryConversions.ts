import {
    isAnyPropertyfilter,
    isHogQLPropertyFilter,
    normalizePropertyFilterValue,
} from 'lib/components/PropertyFilters/utils'
import {
    isActionFilter,
    isEventFilter,
    isLogEntryPropertyFilter,
    isRecordingPropertyFilter,
    isUniversalGroupFilterLike,
} from 'lib/components/UniversalFilters/utils'
import { isString } from 'lib/utils/guards'

import { NodeKind, RecordingOrder, RecordingsQuery, VALID_RECORDING_ORDERS } from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterValue,
    PropertyOperator,
    RecordingDurationFilter,
    RecordingUniversalFilters,
    UniversalFiltersGroup,
    UniversalFiltersGroupValue,
} from '~/types'

import { filtersFromUniversalFilterGroups } from '../utils'

export const DEFAULT_RECORDING_FILTERS_ORDER_BY = 'start_time'

const DURATION_KEYS = new Set(['duration', 'active_seconds', 'inactive_seconds'])

/**
 * `RecordingsQuery` carries a single `operand`, but the universal filter is a tree of AND/OR groups
 * whose leaves we flatten. The "match any" toggle normally syncs the outer and inner group types, but
 * the nested-group editor can set OR on the inner group while the outer stays AND. Reading only the
 * outer group would then silently drop the user's "match any" intent. Treat the query as OR when any
 * group in the tree is OR so that intent survives the flattening.
 *
 * Mirror: keep in sync with `_derive_operand` in posthog/session_recordings/playlist_filters.py.
 */
export function deriveOperand(group: UniversalFiltersGroup): FilterLogicalOperator {
    if (group.type === FilterLogicalOperator.Or) {
        return FilterLogicalOperator.Or
    }
    const hasOrDescendant = (group.values ?? []).some(
        (value) => isUniversalGroupFilterLike(value) && deriveOperand(value) === FilterLogicalOperator.Or
    )
    return hasOrDescendant ? FilterLogicalOperator.Or : FilterLogicalOperator.And
}

export function isValidRecordingOrder(order: unknown): boolean {
    return !!order && isString(order) && VALID_RECORDING_ORDERS.includes(order as RecordingOrder)
}

// Normalizes a single property filter's value if it has a multi-select operator.
function normalizePropertyFilter<T extends { operator?: unknown; value?: unknown; type?: unknown }>(filter: T): T {
    if (
        !filter ||
        typeof filter !== 'object' ||
        !('operator' in filter) ||
        !('value' in filter) ||
        ('type' in filter && filter.type === 'cohort')
    ) {
        return filter
    }
    const normalizedValue = normalizePropertyFilterValue(
        filter.value as PropertyFilterValue,
        filter.operator as PropertyOperator | null
    )
    if (normalizedValue !== filter.value) {
        return { ...filter, value: normalizedValue }
    }
    return filter
}

// Normalizes the properties array nested inside an event or action filter.
function normalizeFilterWithNestedProperties<T extends { properties?: AnyPropertyFilter[] }>(filter: T): T {
    if (!filter.properties || !Array.isArray(filter.properties)) {
        return filter
    }
    const normalizedProperties = filter.properties.map((prop) => normalizePropertyFilter(prop) as AnyPropertyFilter)
    const hasChanges = normalizedProperties.some((prop, i) => prop !== filter.properties![i])
    return hasChanges ? { ...filter, properties: normalizedProperties } : filter
}

export function convertUniversalFiltersToRecordingsQuery(universalFilters: RecordingUniversalFilters): RecordingsQuery {
    const filters = filtersFromUniversalFilterGroups(universalFilters)

    const events: RecordingsQuery['events'] = []
    const actions: RecordingsQuery['actions'] = []
    const properties: RecordingsQuery['properties'] = []
    const console_log_filters: RecordingsQuery['console_log_filters'] = []
    const having_predicates: RecordingsQuery['having_predicates'] = []
    let comment_text: RecordingsQuery['comment_text'] = undefined

    // it was possible to store an invalid order key in local storage sometimes, let's just ignore that instead of erroring
    const order: RecordingsQuery['order'] = isValidRecordingOrder(universalFilters.order)
        ? universalFilters.order
        : DEFAULT_RECORDING_FILTERS_ORDER_BY
    const order_direction: RecordingsQuery['order_direction'] = universalFilters.order_direction || 'DESC'

    // Push every duration filter — a scanner query can carry more than one, and the inverse extracts them all.
    if (universalFilters.duration.length > 0) {
        having_predicates.push(...universalFilters.duration)
    }

    filters.forEach((f) => {
        if (isEventFilter(f)) {
            events.push(normalizeFilterWithNestedProperties(f))
        } else if (isActionFilter(f)) {
            actions.push(normalizeFilterWithNestedProperties(f))
        } else if (isLogEntryPropertyFilter(f)) {
            console_log_filters.push(f)
        } else if (isHogQLPropertyFilter(f)) {
            properties.push(f)
        } else if (isAnyPropertyfilter(f)) {
            if (isRecordingPropertyFilter(f)) {
                if (f.key === 'visited_page') {
                    // Pass visited_page as a recording property to use all_urls array in backend
                    // This filters by URLs that actually appear in the recording, not just events during the session
                    properties.push(f)
                } else if (f.key === 'snapshot_source' && f.value) {
                    having_predicates.push(f)
                } else if (f.key === 'comment_text') {
                    comment_text = f
                } else {
                    having_predicates.push(f)
                }
            } else {
                // Normalize filter value to ensure multi-select operators have array values
                // Skip cohort filters as they have a different value type (number)
                const normalizedValue =
                    f.type !== 'cohort' ? normalizePropertyFilterValue(f.value, f.operator) : f.value

                // Only create a new object if the value actually changed
                if (normalizedValue !== f.value) {
                    properties.push({ ...f, value: normalizedValue } as AnyPropertyFilter)
                } else {
                    properties.push(f)
                }
            }
        }
    })

    return {
        kind: NodeKind.RecordingsQuery,
        order: order,
        order_direction: order_direction,
        date_from: universalFilters.date_from,
        date_to: universalFilters.date_to,
        properties,
        events,
        actions,
        console_log_filters,
        having_predicates,
        comment_text,
        filter_test_accounts: universalFilters.filter_test_accounts,
        operand: deriveOperand(universalFilters.filter_group),
        limit: universalFilters.limit,
        session_ids: universalFilters.session_ids,
    }
}

/**
 * Inverse of {@link convertUniversalFiltersToRecordingsQuery}: unpacks a stored `RecordingsQuery` back into
 * the `RecordingUniversalFilters` the editor renders. Replay Vision persists the query shape, so it round-trips
 * through this on load; the recordings list persists the universal shape and never needs it.
 */
export function recordingsQueryToUniversalFilters(
    query: RecordingsQuery | null | undefined
): RecordingUniversalFilters {
    // having_predicates mixes duration filters (their own control) with recording properties (e.g. snapshot_source).
    const isDuration = (p: AnyPropertyFilter): boolean => p.type === 'recording' && DURATION_KEYS.has(p.key)
    const havingPredicates = query?.having_predicates ?? []

    const values = [
        ...(query?.events ?? []),
        ...(query?.actions ?? []),
        ...(query?.properties ?? []),
        ...(query?.console_log_filters ?? []),
        ...havingPredicates.filter((p) => !isDuration(p)),
        ...(query?.comment_text ? [query.comment_text] : []),
    ] as UniversalFiltersGroupValue[]

    return {
        duration: havingPredicates.filter(isDuration) as RecordingDurationFilter[],
        filter_test_accounts: query?.filter_test_accounts ?? false,
        // Outer group (preserving the stored AND/OR operand) wraps a single inner AND group — the nesting
        // UniversalFilters expects. Without carrying `operand` through, an OR query would silently save back as AND.
        filter_group: {
            type: (query?.operand as FilterLogicalOperator) ?? FilterLogicalOperator.And,
            values: [{ type: FilterLogicalOperator.And, values }],
        },
    }
}
