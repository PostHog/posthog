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

export const defaultDataTableGroupColumns: HogQLExpression[] = ['group_name', 'key', 'created_at']

export const defaultDataTableSessionColumns: HogQLExpression[] = [
    'session_id',
    '$start_timestamp',
    '$end_timestamp',
    '$session_duration',
    '$entry_current_url',
    '$pageview_count',
    '$is_bounce',
]

export function defaultDataTableColumns(kind: NodeKind): HogQLExpression[] {
    return kind === NodeKind.PersonsNode || kind === NodeKind.ActorsQuery
        ? defaultDataTablePersonColumns
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

/** Extract AS alias from SQL expression (e.g., "expr AS foo" -> "foo") */
export function extractAsAlias(query: string): string | null {
    if (!query || typeof query !== 'string') {
        return null
    }
    const trimmed = query.trim()
    if (!trimmed) {
        return null
    }

    // Match: whitespace + AS (case-insensitive) + whitespace + (backticked or word alias), optionally followed by comment
    const asMatch = trimmed.match(/\s+[Aa][Ss]\s+(`[^`]+`|[\w\u0080-\uFFFF]+)(\s*--.*)?$/)
    if (asMatch) {
        const alias = asMatch[1]
        return alias.startsWith('`') && alias.endsWith('`') ? alias.slice(1, -1) : alias
    }
    return null
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
