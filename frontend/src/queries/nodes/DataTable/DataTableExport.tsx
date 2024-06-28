import { IconDownload } from '@posthog/icons'
import { LemonButton, LemonMenu, lemonToast } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TriggerExportProps } from 'lib/components/ExportButton/exporter'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import Papa from 'papaparse'
import { asDisplay } from 'scenes/persons/person-utils'

import {
    defaultDataTableColumns,
    extractExpressionComment,
    removeExpressionComment,
} from '~/queries/nodes/DataTable/utils'
import { getPersonsEndpoint } from '~/queries/query'
import { DataNode, DataTableNode } from '~/queries/schema'
import { isActorsQuery, isEventsQuery, isHogQLQuery, isPersonsNode } from '~/queries/utils'
import { ExporterFormat } from '~/types'

import { dataTableLogic, DataTableRow } from './dataTableLogic'

// Sync with posthog/hogql/constants.py
export const MAX_SELECT_RETURNED_ROWS = 50000

const columnDisallowList = ['person.$delete', '*']

export async function startDownload(
    query: DataTableNode,
    onlySelectedColumns: boolean,
    exportCall: (exportData: TriggerExportProps) => void,
    format: ExporterFormat = ExporterFormat.CSV
): Promise<void> {
    const exportContext = isPersonsNode(query.source)
        ? { path: getPersonsEndpoint(query.source) }
        : { source: query.source }
    if (!exportContext) {
        throw new Error('Unsupported node type')
    }

    if (onlySelectedColumns) {
        exportContext['columns'] = (
            (isEventsQuery(query.source) || isActorsQuery(query.source) ? query.source.select : null) ??
            query.columns ??
            defaultDataTableColumns(query.source.kind)
        )?.filter((c) => c !== 'person.$delete')

        if (isEventsQuery(query.source)) {
            exportContext['columns'] = exportContext['columns'].map((c: string) =>
                removeExpressionComment(c) === 'person' ? 'person.properties.email' : c
            )
        } else if (isPersonsNode(query.source)) {
            exportContext['columns'] = exportContext['columns'].map((c: string) =>
                removeExpressionComment(c) === 'person' ? 'email' : c
            )
        }
        if (exportContext['columns'].includes('person')) {
            exportContext['columns'] = exportContext['columns'].map((c: string) => (c === 'person' ? 'person.id' : c))
        }
        exportContext['columns'] = exportContext['columns'].filter((n: string) => !columnDisallowList.includes(n))
    }
    exportCall({
        export_format: format,
        export_context: exportContext,
    })
}

const getCsvTableData = (dataTableRows: DataTableRow[], columns: string[], query: DataTableNode): string[][] => {
    if (isPersonsNode(query.source)) {
        const filteredColumns = columns.filter((n) => !columnDisallowList.includes(n))

        const csvData = dataTableRows.map((n) => {
            const record = n.result as Record<string, any> | undefined
            const recordWithPerson = { ...(record ?? {}), person: record?.name }

            return filteredColumns.map((n) => recordWithPerson[n])
        })

        return [filteredColumns, ...csvData]
    }

    if (isEventsQuery(query.source)) {
        const filteredColumns = columns
            .filter((n) => !columnDisallowList.includes(n))
            .map((n) => extractExpressionComment(n))

        const csvData = dataTableRows.map((n) => {
            return columns
                .map((col, colIndex) => {
                    if (columnDisallowList.includes(col)) {
                        return null
                    }

                    if (col === 'person') {
                        return asDisplay(n.result?.[colIndex])
                    }

                    return n.result?.[colIndex]
                })
                .filter(Boolean)
        })

        return [filteredColumns, ...csvData]
    }

    if (isHogQLQuery(query.source)) {
        return [columns, ...dataTableRows.map((n) => (n.result as any[]) ?? [])]
    }

    return []
}

const getJsonTableData = (
    dataTableRows: DataTableRow[],
    columns: string[],
    query: DataTableNode
): Record<string, any>[] => {
    if (isPersonsNode(query.source)) {
        const filteredColumns = columns.filter((n) => !columnDisallowList.includes(n))

        return dataTableRows.map((n) => {
            const record = n.result as Record<string, any> | undefined
            const recordWithPerson = { ...(record ?? {}), person: record?.name }

            return filteredColumns.reduce((acc, cur) => {
                acc[cur] = recordWithPerson[cur]
                return acc
            }, {} as Record<string, any>)
        })
    }

    if (isEventsQuery(query.source)) {
        return dataTableRows.map((n) => {
            return columns.reduce((acc, col, colIndex) => {
                if (columnDisallowList.includes(col)) {
                    return acc
                }

                if (col === 'person') {
                    acc[col] = asDisplay(n.result?.[colIndex])
                    return acc
                }

                const colName = extractExpressionComment(col)

                acc[colName] = n.result?.[colIndex]

                return acc
            }, {} as Record<string, any>)
        })
    }

    if (isHogQLQuery(query.source)) {
        return dataTableRows.map((n) => {
            const data = n.result ?? {}
            return columns.reduce((acc, cur, index) => {
                acc[cur] = data[index]
                return acc
            }, {} as Record<string, any>)
        })
    }

    return []
}

function copyTableToCsv(dataTableRows: DataTableRow[], columns: string[], query: DataTableNode): void {
    try {
        const tableData = getCsvTableData(dataTableRows, columns, query)

        const csv = Papa.unparse(tableData)

        void copyToClipboard(csv, 'table')
    } catch {
        lemonToast.error('Copy failed!')
    }
}

function copyTableToJson(dataTableRows: DataTableRow[], columns: string[], query: DataTableNode): void {
    try {
        const tableData = getJsonTableData(dataTableRows, columns, query)

        const json = JSON.stringify(tableData, null, 4)

        void copyToClipboard(json, 'table')
    } catch {
        lemonToast.error('Copy failed!')
    }
}

interface DataTableExportProps {
    query: DataTableNode
    setQuery?: (query: DataTableNode) => void
}

export function DataTableExport({ query }: DataTableExportProps): JSX.Element | null {
    const { dataTableRows, columnsInResponse, columnsInQuery, queryWithDefaults } = useValues(dataTableLogic)
    const { startExport } = useActions(exportsLogic)

    const source: DataNode = query.source
    const filterCount =
        (isEventsQuery(source) || isPersonsNode(source) ? source.properties?.length || 0 : 0) +
        (isEventsQuery(source) && source.event ? 1 : 0) +
        (isPersonsNode(source) && source.search ? 1 : 0)
    const canExportAllColumns =
        (isEventsQuery(source) && source.select.includes('*')) || isPersonsNode(source) || isActorsQuery(source)
    const showExportClipboardButtons = isPersonsNode(source) || isEventsQuery(source) || isHogQLQuery(source)

    return (
        <LemonMenu
            items={[
                {
                    label: 'Export current columns',
                    items: [
                        {
                            label: 'CSV',
                            onClick: () => {
                                void startDownload(query, true, startExport)
                            },
                        },
                        {
                            label: 'XLSX',
                            onClick: () => {
                                void startDownload(query, true, startExport, ExporterFormat.XLSX)
                            },
                        },
                    ],
                },
                canExportAllColumns && {
                    label: 'Export all columns',
                    items: [
                        {
                            label: 'CSV',
                            onClick: () => void startDownload(query, false, startExport),
                        },
                        {
                            label: 'XLSX',
                            onClick: () => void startDownload(query, false, startExport, ExporterFormat.XLSX),
                        },
                    ],
                },
                showExportClipboardButtons && {
                    label: 'Copy to clipboard',
                    items: [
                        {
                            label: 'CSV',
                            onClick: () => {
                                if (dataTableRows) {
                                    copyTableToCsv(
                                        dataTableRows,
                                        columnsInResponse ?? columnsInQuery,
                                        queryWithDefaults
                                    )
                                }
                            },
                            'data-attr': 'copy-csv-to-clipboard',
                        },
                        {
                            label: 'JSON',
                            onClick: () => {
                                if (dataTableRows) {
                                    copyTableToJson(
                                        dataTableRows,
                                        columnsInResponse ?? columnsInQuery,
                                        queryWithDefaults
                                    )
                                }
                            },
                            'data-attr': 'copy-json-to-clipboard',
                        },
                    ],
                },
            ].filter(Boolean)}
        >
            <LemonButton type="secondary" icon={<IconDownload />} data-attr="data-table-export-menu">
                Export{filterCount > 0 ? ` (${filterCount} filter${filterCount === 1 ? '' : 's'})` : ''}
            </LemonButton>
        </LemonMenu>
    )
}
