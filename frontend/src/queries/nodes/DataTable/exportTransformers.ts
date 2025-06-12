import { removeExpressionComment } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, EventsQuery } from '~/queries/schema/schema-general'
import { isEventsQuery } from '~/queries/utils'

/**
 * Transform columns to optimize for export performance.
 * This replaces heavy columns (like full person objects) with lighter alternatives.
 */
export function transformColumnsForExport(columns: string[]): string[] {
    return columns.map((column) => {
        const cleanColumn = removeExpressionComment(column)

        // Replace 'person' with 'person.properties.email' for performance
        if (cleanColumn === 'person') {
            return column.replace(/\bperson\b/, 'person.properties.email')
        }

        return column
    })
}

/**
 * Transform a query source to optimize for export performance.
 * This creates a new query object with optimized select columns.
 */
export function transformQuerySourceForExport(source: EventsQuery): EventsQuery {
    if (!isEventsQuery(source)) {
        return source
    }

    return {
        ...source,
        select: transformColumnsForExport(source.select),
    }
}

/**
 * Check if a DataTable query should use export optimizations.
 * Currently applies to event queries with person columns.
 */
export function shouldOptimizeForExport(query: DataTableNode): boolean {
    if (!isEventsQuery(query.source)) {
        return false
    }

    const allColumns = [...(query.source.select || []), ...(query.columns || [])]

    return allColumns.some((col) => removeExpressionComment(col) === 'person')
}
