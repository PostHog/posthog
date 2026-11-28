import {
    copyTableToCsv,
    copyTableToExcel,
    copyTableToJson,
    copyTableToMarkdown,
} from '~/queries/nodes/DataTable/clipboardUtils'
import { DataTableRow } from '~/queries/nodes/DataTable/dataTableLogic'
import { type DataTableNode, type HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { ExporterFormat } from '~/types'

/** The formats the results can be copied as, in the order the copy menus list them. */
export const RESULTS_COPY_FORMATS = {
    [ExporterFormat.CSV]: { label: 'CSV', copyFn: copyTableToCsv },
    [ExporterFormat.JSON]: { label: 'JSON', copyFn: copyTableToJson },
    [ExporterFormat.XLSX]: { label: 'Excel', copyFn: copyTableToExcel },
    [ExporterFormat.MARKDOWN]: { label: 'Markdown', copyFn: copyTableToMarkdown },
}

const createDataTableQuery = (): DataTableNode => ({
    kind: NodeKind.DataTableNode,
    source: {
        kind: NodeKind.HogQLQuery,
        query: '',
    },
})

/**
 * Transforms DataTable format back to DataTableRow format for clipboard operations
 */
function transformDataTableToDataTableRows(rows: Record<string, any>[], columns: string[]): DataTableRow[] {
    if (!columns.length || !rows.length) {
        return []
    }

    return rows.map((row) => ({
        result: columns.map((col, index) => {
            // Handle both direct column access and column_index format
            const columnKey = `${col}_${index}`
            return row[columnKey] !== undefined ? row[columnKey] : row[col]
        }),
    }))
}

/** Copies the grid's rows to the clipboard in one of RESULTS_COPY_FORMATS. Does nothing without rows. */
export function copyResults(
    format: keyof typeof RESULTS_COPY_FORMATS,
    response: HogQLQueryResponse | undefined,
    rows: Record<string, any>[]
): void {
    if (response?.columns && rows.length > 0) {
        RESULTS_COPY_FORMATS[format].copyFn(
            transformDataTableToDataTableRows(rows, response.columns),
            response.columns,
            createDataTableQuery()
        )
    }
}
