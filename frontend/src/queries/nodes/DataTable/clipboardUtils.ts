import Papa from 'papaparse'

import { lemonToast } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { asDisplay } from 'scenes/persons/person-utils'
import { getDisplayColumnName } from 'scenes/web-analytics/tiles/WebAnalyticsTile'

import { extractExpressionComment } from '~/queries/nodes/DataTable/utils'
import { DataTableNode } from '~/queries/schema/schema-general'
import {
    isEventsQuery,
    isHogQLQuery,
    isMarketingAnalyticsTableQuery,
    isPersonsNode,
    isWebExternalClicksQuery,
    isWebGoalsQuery,
    isWebStatsTableQuery,
} from '~/queries/utils'

import { DataTableRow } from './dataTableLogic'

const columnDisallowList = [
    'person.$delete',
    '*',
    'cross_sell',
    'ui_fill_fraction',
    'context.columns.cross_sell',
    'context.columns.ui_fill_fraction',
]

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

// Helper function to process a single row and return flattened data
const processRowData = (row: DataTableRow, columns: string[], query: DataTableNode): Record<string, any> => {
    const flattenedRecord: Record<string, any> = {}

    if (
        isHogQLQuery(query.source) ||
        isMarketingAnalyticsTableQuery(query.source) ||
        isWebStatsTableQuery(query.source) ||
        isWebGoalsQuery(query.source) ||
        isWebExternalClicksQuery(query.source)
    ) {
        const data = row.result ?? {}
        columns.forEach((col, index) => {
            const value = Array.isArray(data) ? data[index] : (data as Record<string, any>)[index]
            if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
                Object.assign(flattenedRecord, flattenObject(value, col))
            } else {
                flattenedRecord[col] = value
            }
        })
    } else if (isEventsQuery(query.source)) {
        columns.forEach((col, colIndex) => {
            if (columnDisallowList.includes(col)) {
                return
            }

            let value = Array.isArray(row.result)
                ? row.result[colIndex]
                : (row.result as Record<string, any>)?.[colIndex]
            const colName = extractExpressionComment(col)

            if (col === 'person') {
                value = asDisplay(value)
                flattenedRecord[colName] = value
            } else if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
                Object.assign(flattenedRecord, flattenObject(value, colName))
            } else {
                flattenedRecord[colName] = value
            }
        })
    } else if (isPersonsNode(query.source)) {
        const record = row.result as Record<string, any> | undefined
        const recordWithPerson = { ...record, person: record?.name } as Record<string, any>
        const filteredColumns = columns.filter((n) => !columnDisallowList.includes(n))

        filteredColumns.forEach((col) => {
            const value = recordWithPerson[col]
            if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
                Object.assign(flattenedRecord, flattenObject(value, col))
            } else {
                flattenedRecord[col] = value
            }
        })
    }

    return flattenedRecord
}

export const getCsvTableData = (
    dataTableRows: DataTableRow[],
    columns: string[],
    query: DataTableNode,
    preferredColumnOrder?: string[]
): string[][] => {
    // Handle empty data or unsupported query types
    if (dataTableRows.length === 0) {
        return []
    }

    // Process all rows and collect all possible columns
    const allColumnsSet = new Set<string>()
    const processedRows = dataTableRows.map((row) => {
        const flattenedRecord = processRowData(row, columns, query)
        Object.keys(flattenedRecord).forEach((col) => allColumnsSet.add(col))
        return flattenedRecord
    })

    // If no columns were discovered, return empty result
    if (allColumnsSet.size === 0) {
        return []
    }

    // Determine column order: use preferred order if provided, otherwise alphabetical sort
    let orderedColumns: string[]
    if (preferredColumnOrder) {
        // Use preferred order, filtering out disallowed columns and non-existent columns
        orderedColumns = preferredColumnOrder.filter(
            (col) => !columnDisallowList.includes(col) && allColumnsSet.has(col)
        )
    } else {
        // Default behavior: alphabetically sort all discovered columns
        orderedColumns = Array.from(allColumnsSet)
            .filter((col) => !columnDisallowList.includes(col))
            .sort()
    }

    // If no valid columns remain, return empty result
    if (orderedColumns.length === 0) {
        return []
    }

    // Apply UI-friendly column names for web analytics queries
    let displayColumns = orderedColumns
    if (isWebStatsTableQuery(query.source) || isWebGoalsQuery(query.source) || isWebExternalClicksQuery(query.source)) {
        const breakdownBy = isWebStatsTableQuery(query.source) ? query.source.breakdownBy : undefined
        displayColumns = orderedColumns.map((col) => getDisplayColumnName(col, breakdownBy))
    }

    const csvData = processedRows.map((flattenedRecord) => orderedColumns.map((col) => flattenedRecord[col] ?? ''))

    return [displayColumns, ...csvData]
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

    if (
        isHogQLQuery(query.source) ||
        isMarketingAnalyticsTableQuery(query.source) ||
        isWebStatsTableQuery(query.source) ||
        isWebGoalsQuery(query.source) ||
        isWebExternalClicksQuery(query.source)
    ) {
        return dataTableRows.map((n) => {
            const data = n.result ?? {}
            return columns.reduce(
                (acc, cur, index) => {
                    if (columnDisallowList.includes(cur)) {
                        return acc
                    }
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
    preferredColumnOrder?: string[]
): void {
    try {
        const tableData = getCsvTableData(dataTableRows, columns, query, preferredColumnOrder)

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

export function copyTableToExcel(
    dataTableRows: DataTableRow[],
    columns: string[],
    query: DataTableNode,
    preferredColumnOrder?: string[]
): void {
    try {
        const tableData = getCsvTableData(dataTableRows, columns, query, preferredColumnOrder)

        const tsv = Papa.unparse(tableData, { delimiter: '\t' })

        void copyToClipboard(tsv, 'table')
    } catch {
        lemonToast.error('Copy failed!')
    }
}
