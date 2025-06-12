import { removeExpressionComment } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, EventsQuery } from '~/queries/schema/schema-general'
import { isEventsQuery } from '~/queries/utils'

const PERSON_COLUMN = 'person'
const PERSON_EMAIL_COLUMN = 'person.properties.email'

/**
 * Replaces the person column with the email column for performance reasons
 */
export function transformColumnsForExport(columns: string[]): string[] {
    return columns.map((column) => {
        const cleanColumn = removeExpressionComment(column)

        // Replace 'person' with 'person.properties.email' for performance
        if (cleanColumn === PERSON_COLUMN) {
            return column.replace(/\bperson\b/, PERSON_EMAIL_COLUMN)
        }

        return column
    })
}

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

    return allColumns.some((col) => removeExpressionComment(col) === PERSON_COLUMN)
}
