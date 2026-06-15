import { PERSON_DISPLAY_NAME_COLUMN_NAME } from 'lib/constants'

import { QueryFeature, getQueryFeatures } from '~/queries/nodes/DataTable/queryFeatures'
import { DataNode, DataTableNode, EventsQuery, HogQLExpression, NodeKind } from '~/queries/schema/schema-general'

export const defaultDataTableEventColumns: HogQLExpression[] = [
    '*',
    'event',
    PERSON_DISPLAY_NAME_COLUMN_NAME,
    'coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen',
    'properties.$lib',
    'timestamp',
]

export const defaultDataTablePersonColumns: HogQLExpression[] = [PERSON_DISPLAY_NAME_COLUMN_NAME, 'id', 'created_at']

export function getDefaultDataTablePersonColumns(personLastSeenAtEnabled: boolean): HogQLExpression[] {
    const columns = [...defaultDataTablePersonColumns]
    if (personLastSeenAtEnabled) {
        columns.push('last_seen_at')
    }
    return columns
}

export const defaultDataTableGroupColumns: HogQLExpression[] = ['group_name', 'created_at']

export const defaultDataTableSessionColumns: HogQLExpression[] = [
    'session_id',
    'session.distinct_id -- Distinct ID',
    '$start_timestamp',
    '$end_timestamp',
    '$session_duration',
    '$entry_current_url',
    '$pageview_count',
    '$is_bounce',
]

export function defaultDataTableColumns(
    kind: NodeKind,
    personLastSeenAtEnabled: boolean = false // Temporary, until last_seen_at is enabled for everyone
): HogQLExpression[] {
    return kind === NodeKind.PersonsNode || kind === NodeKind.ActorsQuery
        ? getDefaultDataTablePersonColumns(personLastSeenAtEnabled)
        : kind === NodeKind.EventsQuery
          ? defaultDataTableEventColumns
          : kind === NodeKind.SessionsQuery
            ? defaultDataTableSessionColumns
            : kind === NodeKind.EventsNode
              ? defaultDataTableEventColumns.filter((c) => c !== '*')
              : kind === NodeKind.GroupsQuery
                ? defaultDataTableGroupColumns
                : []
}

export function getDataNodeDefaultColumns(source: DataNode): HogQLExpression[] {
    if (
        getQueryFeatures(source).has(QueryFeature.selectAndOrderByColumns) &&
        Array.isArray((source as EventsQuery).select) &&
        (source as EventsQuery).select.length > 0
    ) {
        return (source as EventsQuery).select
    }
    return defaultDataTableColumns(source.kind)
}

export function getColumnsForQuery(query: DataTableNode): HogQLExpression[] {
    return query.columns ?? getDataNodeDefaultColumns(query.source)
}

export function extractExpressionComment(query: string): string {
    if (query.includes('--')) {
        return query.split('--').pop()?.trim() || query
    }
    return query
}

/**
 * Strip a trailing `AS <alias>` clause from a HogQL/SQL expression.
 * Handles backticked, double-quoted, and bare-word aliases, with an optional
 * trailing `-- comment`. The trailing `$` anchor prevents accidental matches
 * inside string literals.
 */
export function removeAsAlias(query: string): string {
    if (!query || typeof query !== 'string') {
        return query
    }
    return query.replace(/\s+[Aa][Ss]\s+(`[^`]+`|"[^"]+"|[\w\u0080-\uFFFF]+)(\s*--.*)?$/, '')
}

/** Extract AS alias from SQL expression (e.g., "expr AS foo" -> "foo") */
export function extractAsAlias(query: string): string | null {
    if (!query || typeof query !== 'string') {
        return null
    }
    const trimmed = query.trim()
    if (!trimmed) {
        return null
    }

    // Match: whitespace + AS (case-insensitive) + whitespace + (backticked, double-quoted, or word alias),
    // optionally followed by comment. Per the HogQL grammar, both `backticks` and "double quotes" delimit
    // quoted identifiers, so both forms are valid alias delimiters.
    const asMatch = trimmed.match(/\s+[Aa][Ss]\s+(`[^`]+`|"[^"]+"|[\w\u0080-\uFFFF]+)(\s*--.*)?$/)
    if (asMatch) {
        const alias = asMatch[1]
        if ((alias.startsWith('`') && alias.endsWith('`')) || (alias.startsWith('"') && alias.endsWith('"'))) {
            return alias.slice(1, -1)
        }
        return alias
    }
    return null
}

/**
 * Resolve a column header `key` to a HogQL expression suitable for ORDER BY.
 *
 * The events query response returns resolved alias names (e.g. `Absolute Time`)
 * for aliased columns, which is what we get as `key` when the user clicks Sort.
 * But events ORDER BY does not resolve SELECT aliases by name — it needs the
 * underlying expression. Look up the matching raw select entry, then strip the
 * trailing AS clause to ORDER BY the bare expression.
 */
export function orderByForSelectKey(key: string, select: readonly string[]): string {
    const matchingRaw = select.find((s) => s === key) ?? select.find((s) => extractAsAlias(s) === key) ?? key
    return removeAsAlias(matchingRaw)
}

/** Get display label for an expression, trying AS alias first, then comment syntax */
export function extractDisplayLabel(query: string): string {
    if (!query || typeof query !== 'string') {
        return query
    }
    // Parse `expr AS column` first, fallback to `expr -- column`
    return extractAsAlias(query) ?? extractExpressionComment(query)
}

export function removeExpressionComment(query: string): string {
    if (query.includes('--')) {
        return query.split('--').slice(0, -1).join('--').trim()
    }
    return query.trim()
}
