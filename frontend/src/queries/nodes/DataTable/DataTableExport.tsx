import Papa from 'papaparse'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { IconExport } from 'lib/lemon-ui/icons'
import { triggerExport } from 'lib/components/ExportButton/exporter'
import { ExporterFormat } from '~/types'
import { DataNode, DataTableNode, NodeKind } from '~/queries/schema'
import {
    defaultDataTableColumns,
    extractExpressionComment,
    removeExpressionComment,
} from '~/queries/nodes/DataTable/utils'
import { isEventsQuery, isHogQLQuery, isPersonsNode } from '~/queries/utils'
import { getPersonsEndpoint } from '~/queries/query'
import { ExportWithConfirmation } from '~/queries/nodes/DataTable/ExportWithConfirmation'
import { DataTableRow, dataTableLogic } from './dataTableLogic'
import { useValues } from 'kea'
import { LemonDivider, lemonToast } from '@posthog/lemon-ui'
import { asDisplay } from 'scenes/persons/person-utils'
import { urls } from 'scenes/urls'
import { copyToClipboard } from 'lib/utils'

const EXPORT_MAX_LIMIT = 10000

async function startDownload(query: DataTableNode, onlySelectedColumns: boolean): Promise<void> {
    const exportContext = isPersonsNode(query.source)
        ? { path: getPersonsEndpoint(query.source) }
        : { source: query.source }
    if (!exportContext) {
        throw new Error('Unsupported node type')
    }

    if (onlySelectedColumns) {
        exportContext['columns'] = (
            (isEventsQuery(query.source) ? query.source.select : null) ??
            query.columns ??
            defaultDataTableColumns(query.source.kind)
        )?.filter((c) => c !== 'person.$delete')

        if (isEventsQuery(query.source)) {
            exportContext['columns'] = exportContext['columns'].map((c: string) =>
                removeExpressionComment(c) === 'person' ? 'person.properties.email' : c
            )
        } else if (isPersonsNode(query.source)) {
            exportContext['columns'] = exportContext['columns'].map((c: string) =>
                removeExpressionComment(c) === 'person' ? 'properties.email' : c
            )
        }
    }
    await triggerExport({
        export_format: ExporterFormat.CSV,
        export_context: exportContext,
    })
}

const columnDisallowList = ['person.$delete', '*']
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
    const { dataTableRows, columnsInResponse, columnsInQuery, queryWithDefaults, response } = useValues(dataTableLogic)

    const source: DataNode = query.source
    const filterCount =
        (isEventsQuery(source) || isPersonsNode(source) ? source.properties?.length || 0 : 0) +
        (isEventsQuery(source) && source.event ? 1 : 0) +
        (isPersonsNode(source) && source.search ? 1 : 0)
    const canExportAllColumns = (isEventsQuery(source) && source.select.includes('*')) || isPersonsNode(source)
    const showExportClipboardButtons = isPersonsNode(source) || isEventsQuery(source) || isHogQLQuery(source)

    return (
        <LemonButtonWithDropdown
            dropdown={{
                sameWidth: false,
                closeOnClickInside: false,
                overlay: [
                    <ExportWithConfirmation
                        key={1}
                        placement={'topRight'}
                        onConfirm={() => {
                            void startDownload(query, true)
                        }}
                        actor={isPersonsNode(query.source) ? 'persons' : 'events'}
                        limit={EXPORT_MAX_LIMIT}
                    >
                        <LemonButton fullWidth status="stealth">
                            Export current columns
                        </LemonButton>
                    </ExportWithConfirmation>,
                ]
                    .concat(
                        canExportAllColumns
                            ? [
                                  <ExportWithConfirmation
                                      key={0}
                                      placement={'topRight'}
                                      onConfirm={() => void startDownload(query, false)}
                                      actor={isPersonsNode(query.source) ? 'persons' : 'events'}
                                      limit={EXPORT_MAX_LIMIT}
                                  >
                                      <LemonButton fullWidth status="stealth">
                                          Export all columns
                                      </LemonButton>
                                  </ExportWithConfirmation>,
                              ]
                            : []
                    )
                    .concat(
                        showExportClipboardButtons
                            ? [
                                  <LemonDivider key={2} />,
                                  <LemonButton
                                      key={3}
                                      fullWidth
                                      status="stealth"
                                      data-attr={'copy-csv-to-clipboard'}
                                      onClick={() => {
                                          if (dataTableRows) {
                                              copyTableToCsv(
                                                  dataTableRows,
                                                  columnsInResponse ?? columnsInQuery,
                                                  queryWithDefaults
                                              )
                                          }
                                      }}
                                  >
                                      Copy CSV to clipboard
                                  </LemonButton>,
                                  <LemonButton
                                      key={4}
                                      fullWidth
                                      status="stealth"
                                      data-attr={'copy-json-to-clipboard'}
                                      onClick={() => {
                                          if (dataTableRows) {
                                              copyTableToJson(
                                                  dataTableRows,
                                                  columnsInResponse ?? columnsInQuery,
                                                  queryWithDefaults
                                              )
                                          }
                                      }}
                                  >
                                      Copy JSON to clipboard
                                  </LemonButton>,
                              ]
                            : []
                    )
                    .concat(
                        queryWithDefaults.showOpenEditorButton
                            ? [
                                  <LemonDivider key={5} />,
                                  <LemonButton
                                      key={6}
                                      fullWidth
                                      status="stealth"
                                      data-attr={'open-json-editor-button'}
                                      to={
                                          query
                                              ? urls.insightNew(undefined, undefined, JSON.stringify(query))
                                              : undefined
                                      }
                                  >
                                      Open table as a new insight
                                  </LemonButton>,
                              ]
                            : []
                    )
                    .concat(
                        response?.hogql
                            ? [
                                  <LemonDivider key={7} />,
                                  <LemonButton
                                      key={8}
                                      fullWidth
                                      status="stealth"
                                      data-attr={'open-sql-editor-button'}
                                      to={urls.insightNew(
                                          undefined,
                                          undefined,
                                          JSON.stringify({
                                              kind: NodeKind.DataTableNode,
                                              full: true,
                                              source: { kind: NodeKind.HogQLQuery, query: response.hogql },
                                          })
                                      )}
                                  >
                                      Edit SQL directly
                                  </LemonButton>,
                              ]
                            : []
                    ),
            }}
            type="secondary"
            icon={<IconExport />}
            data-attr="data-table-export-menu"
        >
            Export{filterCount > 0 ? ` (${filterCount} filter${filterCount === 1 ? '' : 's'})` : ''}
        </LemonButtonWithDropdown>
    )
}
