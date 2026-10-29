import Papa from 'papaparse'

import { lemonToast } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { extractExpressionComment, removeExpressionComment } from '~/queries/nodes/DataTable/utils'
import { DataTableNode } from '~/queries/schema/schema-general'
import {
    isActorsQuery,
    isEventsQuery,
    isHogQLQuery,
    isMarketingAnalyticsTableQuery,
    isPersonsNode,
} from '~/queries/utils'

import { asDisplay } from 'products/persons/frontend/person-utils'

import { DataTableRow } from './dataTableLogic'

export function projectExportRows(rows: DataTableRow[], columns: string[], exportColumns: string[]): DataTableRow[] {
    const indexes = exportColumns.map((column) => columns.indexOf(column))
    return rows.map((row) => {
        const result = row.result
        return Array.isArray(result) ? { ...row, result: indexes.map((index) => result[index]) } : row
    })
}

const columnDisallowList = ['person.$delete', '*']

// Helper function to recursively flatten objects for CSV export
export const flattenObject = (obj: any, prefix?: string, separator = '.'): Record<string, any> => {
    const flattened: Record<string, any> = {}

    if (obj === null || obj === undefined) {
        if (prefix === '') {
            return obj
        }
        return { [prefix || 'value']: obj }
    }

    if (typeof obj !== 'object' || Array.isArray(obj)) {
        if (prefix === '') {
            return obj
        }
        return { [prefix || 'value']: obj }
    }

    // Example: { value: 1, value2: 2, nested: { a: 3, b: 4 } } with prefix 'col'
    // Should produce: { 'col.value': 1, 'col.value2': 2, 'col.nested.a': 3, 'col.nested.b': 4 }

    for (const [key, value] of Object.entries(obj)) {
        const newKey = prefix ? `${prefix}${separator}${key}` : key

        if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
            Object.assign(flattened, flattenObject(value, newKey, separator))
        } else {
            flattened[newKey] = value
        }
    }

    return flattened
}

const flattenCell = (value: any, col: string): Record<string, any> =>
    value !== null && typeof value === 'object' && !Array.isArray(value) ? flattenObject(value, col) : { [col]: value }

// Returns one flattened group per column, so duplicate column names do not overwrite each other
const processRowData = (row: DataTableRow, columns: string[], query: DataTableNode): Record<string, any>[] => {
    if (isHogQLQuery(query.source) || isMarketingAnalyticsTableQuery(query.source)) {
        const data = row.result ?? {}
        return columns.map((col, index) =>
            flattenCell(Array.isArray(data) ? data[index] : (data as Record<string, any>)[index], col)
        )
    } else if (isEventsQuery(query.source) || isActorsQuery(query.source)) {
        return columns.map((col, colIndex) => {
            if (columnDisallowList.includes(col)) {
                return {}
            }

            const value = Array.isArray(row.result)
                ? row.result[colIndex]
                : (row.result as Record<string, any>)?.[colIndex]
            const colName = extractExpressionComment(col)

            if (col === 'person') {
                return { [colName]: asDisplay(value) }
            }
            if (removeExpressionComment(col) === 'person_display_name') {
                return { [colName]: value?.display_name }
            }
            return flattenCell(value, colName)
        })
    } else if (isPersonsNode(query.source)) {
        const record = row.result as Record<string, any> | undefined
        const recordWithPerson = { ...record, person: record?.name } as Record<string, any>

        return columns.map((col) => (columnDisallowList.includes(col) ? {} : flattenCell(recordWithPerson[col], col)))
    }

    return []
}

export const getCsvTableData = (dataTableRows: DataTableRow[], columns: string[], query: DataTableNode): string[][] => {
    // Handle empty data or unsupported query types
    if (dataTableRows.length === 0) {
        return []
    }

    const processedRows = dataTableRows.map((row) => processRowData(row, columns, query))

    // Keep the query column order, and put flattened sub-columns right after their parent column
    const groupKeys = columns.map((_, index) => {
        const keys = new Set<string>()
        processedRows.forEach((groups) => Object.keys(groups[index] ?? {}).forEach((key) => keys.add(key)))
        return Array.from(keys)
    })

    const header = groupKeys.flat()
    if (header.length === 0) {
        return []
    }

    const csvData = processedRows.map((groups) =>
        groupKeys.flatMap((keys, index) => keys.map((key) => groups[index]?.[key] ?? ''))
    )

    return [header, ...csvData]
}

export const getJsonTableData = (
    dataTableRows: DataTableRow[],
    columns: string[],
    query: DataTableNode
): Record<string, any>[] => {
    if (isPersonsNode(query.source)) {
        const filteredColumns = columns.filter((n) => !columnDisallowList.includes(n))

        return dataTableRows.map((n) => {
            const record = n.result as Record<string, any> | undefined
            const recordWithPerson = { ...record, person: record?.name } as Record<string, any>

            return filteredColumns.reduce(
                (acc, cur) => {
                    acc[cur] = recordWithPerson[cur]
                    return acc
                },
                {} as Record<string, any>
            )
        })
    }

    if (isEventsQuery(query.source)) {
        return dataTableRows.map((n) => {
            return columns.reduce(
                (acc, col, colIndex) => {
                    if (columnDisallowList.includes(col)) {
                        return acc
                    }

                    if (col === 'person') {
                        acc[col] = asDisplay(
                            Array.isArray(n.result) ? n.result[colIndex] : (n.result as Record<string, any>)?.[colIndex]
                        )
                        return acc
                    }

                    const colName = extractExpressionComment(col)

                    acc[colName] = Array.isArray(n.result)
                        ? n.result[colIndex]
                        : (n.result as Record<string, any>)?.[colIndex]

                    return acc
                },
                {} as Record<string, any>
            )
        })
    }

    if (isHogQLQuery(query.source) || isMarketingAnalyticsTableQuery(query.source)) {
        return dataTableRows.map((n) => {
            const data = n.result ?? {}
            return columns.reduce(
                (acc, cur, index) => {
                    acc[cur] = Array.isArray(data) ? data[index] : (data as Record<string, any>)[index]
                    return acc
                },
                {} as Record<string, any>
            )
        })
    }

    return []
}

export function copyTableToCsv(
    dataTableRows: DataTableRow[],
    columns: string[],
    query: DataTableNode,
    includeHeader: boolean = true
): void {
    try {
        const tableData = getCsvTableData(dataTableRows, columns, query).slice(includeHeader ? 0 : 1)

        const csv = Papa.unparse(tableData)

        void copyToClipboard(csv, 'table')
    } catch {
        lemonToast.error('Copy failed!')
    }
}

export function copyTableToJson(dataTableRows: DataTableRow[], columns: string[], query: DataTableNode): void {
    try {
        const tableData = getJsonTableData(dataTableRows, columns, query)

        const json = JSON.stringify(tableData, null, 4)

        void copyToClipboard(json, 'table')
    } catch {
        lemonToast.error('Copy failed!')
    }
}

export function copyTableToExcel(dataTableRows: DataTableRow[], columns: string[], query: DataTableNode): void {
    try {
        const tableData = getCsvTableData(dataTableRows, columns, query)

        const tsv = Papa.unparse(tableData, { delimiter: '\t' })

        void copyToClipboard(tsv, 'table')
    } catch {
        lemonToast.error('Copy failed!')
    }
}

export function copyTableToMarkdown(dataTableRows: DataTableRow[], columns: string[], query: DataTableNode): void {
    try {
        const tableData = getCsvTableData(dataTableRows, columns, query)

        if (tableData.length === 0) {
            lemonToast.error('No data to copy!')
            return
        }

        const [headers, ...rows] = tableData
        const escape = (cell: any): string =>
            String(cell ?? '')
                .replace(/\n/g, '\\n')
                .replace(/\r/g, '\\r')
                .replace(/\|/g, '\\|')

        const escapedHeaders = headers.map(escape)
        const escapedRows = rows.map((row) => row.map(escape))

        const colWidths = escapedHeaders.map((header, colIndex) =>
            Math.max(3, header.length, ...escapedRows.map((row) => (row[colIndex] ?? '').length))
        )

        const pad = (cell: string, width: number): string => cell.padEnd(width)

        const headerRow = `| ${escapedHeaders.map((h, i) => pad(h, colWidths[i])).join(' | ')} |`
        const separatorRow = `| ${colWidths.map((w) => '-'.repeat(w)).join(' | ')} |`
        const dataRows = escapedRows.map((row) => `| ${row.map((cell, i) => pad(cell, colWidths[i])).join(' | ')} |`)

        const markdown = [headerRow, separatorRow, ...dataRows].join('\n')

        void copyToClipboard(markdown, 'table')
    } catch {
        lemonToast.error('Copy failed!')
    }
}
