import { DataNode, DataTableNode, HogQLExpression, NodeKind } from '~/queries/schema'
import { isEventsQuery } from '~/queries/utils'

export const defaultDataTableEventColumns: HogQLExpression[] = [
    '*',
    'event',
    'person',
    'coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen',
    'properties.$lib',
    'timestamp',
]

export const defaultDataTablePersonColumns: HogQLExpression[] = ['person', 'id', 'created_at', 'person.$delete']

export function defaultDataTableColumns(kind: NodeKind): HogQLExpression[] {
    return kind === NodeKind.PersonsNode
        ? defaultDataTablePersonColumns
        : kind === NodeKind.EventsQuery
        ? defaultDataTableEventColumns
        : kind === NodeKind.EventsNode
        ? defaultDataTableEventColumns.filter((c) => c !== '*')
        : []
}

export function getDataNodeDefaultColumns(source: DataNode): HogQLExpression[] {
    return (
        (isEventsQuery(source) && Array.isArray(source.select) && source.select.length > 0 ? source.select : null) ??
        defaultDataTableColumns(source.kind)
    )
}

export function getColumnsForQuery(query: DataTableNode): HogQLExpression[] {
    return query.columns ?? getDataNodeDefaultColumns(query.source)
}

/**
 * Extracts the comment and/or alias from a query. For display only!
 *
 * This is a rather naive implementation using basic string operations.
 * Its output is not cleaned for usage in queries!
 */
export function extractCommentOrAlias(query: string): string {
    if (query.match(/ as (`[^`]+`|"[^"]+"|[a-zA-Z$][a-zA-Z0-9_$]*)\s*$/)) {
        const comment = query.split(' as ').pop()?.trim() || query
        if ((comment.startsWith('`') || comment.startsWith('"')) && comment.endsWith(comment[0])) {
            return comment.slice(1, -1)
        }
        return comment
    }
    if (query.includes('--')) {
        return query.split('--').pop()?.trim() || query
    }
    return query
}

/**
 * Removes the comment and/or alias from a query, keeping just the SQL. For display only!
 *
 * This is a rather naive implementation using basic string operations.
 * Its output is not cleaned for usage in queries!
 */
export function removeCommentOrAlias(query: string): string {
    if (query.includes('--')) {
        query = query.split('--').slice(0, -1).join('--').trim()
    }
    if (query.match(/ as (`[^`]+`|"[^"]+"|[a-zA-Z\$][a-zA-Z0-9\_\$]*)$/)) {
        query = query.split(' as ').slice(0, -1).join(' as ').trim()
    }
    return query.trim()
}
