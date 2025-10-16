import { DataTableRow } from '~/queries/nodes/DataTable/dataTableLogic'

/**
 * Transforms DataTable format back to DataTableRow format for clipboard operations
 */
export function transformDataTableToDataTableRows(rows: Record<string, any>[], columns: string[]): DataTableRow[] {
    if (!columns.length || !rows.length) {
        return []
    }

    return rows.map((row) => ({
        result: columns.map((col) => row[col]),
    }))
}
