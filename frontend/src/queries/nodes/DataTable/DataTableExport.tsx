import Papa from 'papaparse'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { IconExport } from 'lib/lemon-ui/icons'
import { triggerExport } from 'lib/components/ExportButton/exporter'
import { ExporterFormat } from '~/types'
import { DataNode, DataTableNode } from '~/queries/schema'
import { defaultDataTableColumns, extractExpressionComment } from '~/queries/nodes/DataTable/utils'
import { isEventsQuery, isHogQLQuery, isPersonsNode } from '~/queries/utils'
import { getPersonsEndpoint } from '~/queries/query'
import { ExportWithConfirmation } from '~/queries/nodes/DataTable/ExportWithConfirmation'
import { DataTableRow, dataTableLogic } from './dataTableLogic'
import { useValues } from 'kea'
import { LemonDivider, lemonToast } from '@posthog/lemon-ui'
import { asDisplay } from 'scenes/persons/person-utils'

const EXPORT_MAX_LIMIT = 10000

function startDownload(query: DataTableNode, onlySelectedColumns: boolean): void {
    const exportContext = isPersonsNode(query.source)
        ? { path: getPersonsEndpoint(query.source), max_limit: EXPORT_MAX_LIMIT }
        : { source: query.source, max_limit: EXPORT_MAX_LIMIT }
    if (!exportContext) {
        throw new Error('Unsupported node type')
    }

    const columnMapping = {
        url: ['properties.$current_url', 'properties.$screen_name'],
        time: 'timestamp',
        event: 'event',
        source: 'properties.$lib',
        person: isPersonsNode(query.source)
            ? ['distinct_ids.0', 'properties.email']
            : ['person.distinct_ids.0', 'person.properties.email'],
    }

    if (onlySelectedColumns) {
        exportContext['columns'] = (query.columns ?? defaultDataTableColumns(query.source.kind))
            ?.flatMap((c) => columnMapping[c] || c)
            .filter((c) => c !== 'person.$delete')
    }
    triggerExport({
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

        navigator.clipboard.writeText(csv).then(() => {
            lemonToast.success('Table copied to clipboard!')
        })
    } catch {
        lemonToast.error('Copy failed!')
    }
}

function copyTableToJson(dataTableRows: DataTableRow[], columns: string[], query: DataTableNode): void {
    try {
        const tableData = getJsonTableData(dataTableRows, columns, query)

        const json = JSON.stringify(tableData, null, 4)

        navigator.clipboard.writeText(json).then(() => {
            lemonToast.success('Table copied to clipboard!')
        })
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

    const source: DataNode = query.source
    const filterCount =
        (isEventsQuery(source) || isPersonsNode(source) ? source.properties?.length || 0 : 0) +
        (isEventsQuery(source) && source.event ? 1 : 0) +
        (isPersonsNode(source) && source.search ? 1 : 0)
    const canExportAllColumns = isEventsQuery(source) || isPersonsNode(source)
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
                            startDownload(query, true)
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
                                      placement={'bottomRight'}
                                      onConfirm={() => startDownload(query, false)}
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
                                      key={3}
                                      fullWidth
                                      status="stealth"
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
                    ),
            }}
            type="secondary"
            icon={<IconExport />}
        >
            Export{filterCount > 0 ? ` (${filterCount} filter${filterCount === 1 ? '' : 's'})` : ''}
        </LemonButtonWithDropdown>
    )
}
