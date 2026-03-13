import { removeExpressionComment } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, EventsQuery } from '~/queries/schema/schema-general'
import { isEventsQuery } from '~/queries/utils'

const PERSON_COLUMN = 'person'

/**
 /**
 * Replaces the person column with a coalesce expression using personDisplayNameProperties for performance reasons
 */
export function transformColumnsForExport(columns: string[], personDisplayNameProperties: string[]): string[] {
    const props = personDisplayNameProperties.map((key) => `person.properties.${key}`)
    const expr = `coalesce(${[...props, 'distinct_id'].join(', ')})`
    return columns.map((column) => {
        const cleanColumn = removeExpressionComment(column)

        // Replace 'person' with coalesce expression for performance
        if (cleanColumn === PERSON_COLUMN) {
            const newColumn = column.replace(/\bperson\b/, expr)
            if (!column.includes('--')) {
                return `${newColumn} -- Person`
            }
            return newColumn
        }

        return column
    })
}

export function transformQuerySourceForExport(source: EventsQuery, personDisplayNameProperties: string[]): EventsQuery {
    if (!isEventsQuery(source)) {
        return source
    }

    return {
        ...source,
        select: transformColumnsForExport(source.select, personDisplayNameProperties),
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
