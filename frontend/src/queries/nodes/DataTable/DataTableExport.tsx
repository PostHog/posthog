import { IconDownload } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonMenu, lemonToast } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TriggerExportProps } from 'lib/components/ExportButton/exporter'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import Papa from 'papaparse'
import { asDisplay } from 'scenes/persons/person-utils'

import {
    shouldOptimizeForExport,
    transformColumnsForExport,
    transformQuerySourceForExport,
} from '~/queries/nodes/DataTable/exportTransformers'
import {
    defaultDataTableColumns,
    extractExpressionComment,
    removeExpressionComment,
} from '~/queries/nodes/DataTable/utils'
import { getPersonsEndpoint } from '~/queries/query'
import { DataNode, DataTableNode } from '~/queries/schema/schema-general'
import {
    isActorsQuery,
    isEventsQuery,
    isHogQLQuery,
    isMarketingAnalyticsTableQuery,
    isPersonsNode,
} from '~/queries/utils'
import { ExporterFormat } from '~/types'

import { dataTableLogic, DataTableRow } from './dataTableLogic'

// Sync with posthog/hogql/constants.py
export const MAX_SELECT_RETURNED_ROWS = 50000

const columnDisallowList = ['person.$delete', '*']

export async function startDownload(
    query: DataTableNode,
    onlySelectedColumns: boolean,
    exportCall: (exportData: TriggerExportProps) => void,
    format: ExporterFormat = ExporterFormat.CSV,
    fileNameForExport?: string
): Promise<void> {
    const shouldOptimize = shouldOptimizeForExport(query)

    let exportSource = query.source

    // Remove person column from the source otherwise export fails when there's 1000+ records
    if (shouldOptimize && isEventsQuery(query.source)) {
        exportSource = transformQuerySourceForExport(query.source)
    }

    const exportContext = isPersonsNode(query.source)
        ? { path: getPersonsEndpoint(query.source) }
        : { source: exportSource }

    if (!exportContext) {
        throw new Error('Unsupported node type')
    }

    if (onlySelectedColumns) {
        let columns = (
            (isEventsQuery(query.source) || isActorsQuery(query.source) ? query.source.select : null) ??
            query.columns ??
            defaultDataTableColumns(query.source.kind)
        )?.filter((c) => c !== 'person.$delete')

        // Apply export optimizations to columns
        if (shouldOptimize && isEventsQuery(query.source)) {
            columns = transformColumnsForExport(columns)
        } else if (isPersonsNode(query.source)) {
            columns = columns.map((c: string) => (removeExpressionComment(c) === 'person' ? 'email' : c))
        }

        if (columns.includes('person')) {
            columns = columns.map((c: string) => (c === 'person' ? 'person.distinct_ids.0' : c))
        }

        columns = columns.filter((n: string) => !columnDisallowList.includes(n))

        exportContext['columns'] = columns
    }
    if (fileNameForExport != null) {
        exportContext['filename'] = fileNameForExport
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
            const recordWithPerson = { ...record, person: record?.name }

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

    if (isHogQLQuery(query.source) || isMarketingAnalyticsTableQuery(query.source)) {
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
            const recordWithPerson = { ...record, person: record?.name }

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

    if (isHogQLQuery(query.source) || isMarketingAnalyticsTableQuery(query.source)) {
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
    fileNameForExport?: string
}

export function DataTableExport({ query, fileNameForExport }: DataTableExportProps): JSX.Element | null {
    const { dataTableRows, columnsInResponse, columnsInQuery, queryWithDefaults } = useValues(dataTableLogic)
    const { startExport, createStaticCohort } = useActions(exportsLogic)

    const source: DataNode = query.source
    const filterCount =
        (isEventsQuery(source) || isPersonsNode(source) ? source.properties?.length || 0 : 0) +
        (isEventsQuery(source) && source.event ? 1 : 0) +
        (isPersonsNode(source) && source.search ? 1 : 0)
    const canExportAllColumns =
        (isEventsQuery(source) && source.select.includes('*')) || isPersonsNode(source) || isActorsQuery(source)
    const showExportClipboardButtons =
        isPersonsNode(source) || isEventsQuery(source) || isHogQLQuery(source) || isMarketingAnalyticsTableQuery(source)
    const canSaveAsCohort = isActorsQuery(source)

    return (
        <LemonMenu
            items={[
                {
                    label: 'Export current columns',
                    items: [
                        {
                            label: 'CSV',
                            onClick: () => {
                                void startDownload(query, true, startExport, ExporterFormat.CSV, fileNameForExport)
                            },
                        },
                        {
                            label: 'XLSX',
                            onClick: () => {
                                void startDownload(query, true, startExport, ExporterFormat.XLSX, fileNameForExport)
                            },
                        },
                    ],
                },
                canExportAllColumns && {
                    label: 'Export all columns',
                    items: [
                        {
                            label: 'CSV',
                            onClick: () =>
                                void startDownload(query, false, startExport, ExporterFormat.CSV, fileNameForExport),
                        },
                        {
                            label: 'XLSX',
                            onClick: () =>
                                void startDownload(query, false, startExport, ExporterFormat.XLSX, fileNameForExport),
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
                canSaveAsCohort && {
                    label: 'Save as cohort',
                    items: [
                        {
                            label: 'Save as static cohort',
                            onClick: () => {
                                LemonDialog.openForm({
                                    title: 'Save as static cohort',
                                    description: 'This will create a cohort with the current list of people.',
                                    initialValues: {
                                        name: '',
                                    },
                                    content: (
                                        <LemonField name="name">
                                            <LemonInput
                                                type="text"
                                                data-attr="insight-name"
                                                placeholder="Name of the new cohort"
                                                autoFocus
                                            />
                                        </LemonField>
                                    ),
                                    errors: {
                                        name: (name) => (!name ? 'You must enter a name' : undefined),
                                    },
                                    onSubmit: async ({ name }) => createStaticCohort(name, source),
                                })
                            },
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
