import { useValues } from 'kea'
import Papa from 'papaparse'

import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonMenu, lemonToast } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { copyTableToCsv, copyTableToExcel, copyTableToJson } from '~/queries/nodes/DataTable/clipboardUtils'
import { DataTableRow } from '~/queries/nodes/DataTable/dataTableLogic'
import {
    DataTableNode,
    InsightVizNode,
    NodeKind,
    QuerySchema,
    WebExternalClicksTableQuery,
    WebGoalsQuery,
    WebStatsTableQuery,
    WebStatsTableQueryResponse,
    WebTrendsMetric,
    WebTrendsQuery,
    WebTrendsQueryResponse,
} from '~/queries/schema/schema-general'
import { isWebExternalClicksQuery, isWebGoalsQuery, isWebStatsTableQuery, isWebTrendsQuery } from '~/queries/utils'
import { getDisplayColumnName } from '~/scenes/web-analytics/tiles/WebAnalyticsTile'
import { ExporterFormat, InsightLogicProps } from '~/types'

import { insightDataLogic } from '../insights/insightDataLogic'

interface WebAnalyticsExportProps {
    query: QuerySchema
    insightProps: InsightLogicProps
}

const webTrendsMetricDisplayNames: Record<WebTrendsMetric, string> = {
    [WebTrendsMetric.UNIQUE_USERS]: 'Visitors',
    [WebTrendsMetric.PAGE_VIEWS]: 'Views',
    [WebTrendsMetric.SESSIONS]: 'Sessions',
    [WebTrendsMetric.BOUNCES]: 'Bounces',
    [WebTrendsMetric.SESSION_DURATION]: 'Session duration',
    [WebTrendsMetric.TOTAL_SESSIONS]: 'Total sessions',
}

function getWebAnalyticsTableData(
    response: WebStatsTableQueryResponse,
    columns: string[],
    query: WebStatsTableQuery | WebGoalsQuery | WebExternalClicksTableQuery
): string[][] {
    if (!response.results || response.results.length === 0 || !columns.length) {
        return []
    }

    const hasComparison = query.compareFilter?.compare === true
    const breakdownBy = isWebStatsTableQuery(query) ? query.breakdownBy : undefined

    // Check which columns have array values (comparison data) by examining the first row
    const firstRow = response.results[0] as any[]
    const columnHasComparison = columns.map((_, colIndex) => Array.isArray(firstRow[colIndex]))

    const displayHeaders = hasComparison
        ? columns.flatMap((col, colIndex) => {
              const displayName = getDisplayColumnName(col, breakdownBy)
              if (columnHasComparison[colIndex]) {
                  return [`${displayName} (current)`, `${displayName} (previous)`]
              }
              return displayName
          })
        : columns.map((col) => getDisplayColumnName(col, breakdownBy))

    const dataRows = response.results.map((result) => {
        const row = result as any[]
        return columns.flatMap((_, colIndex) => {
            const value = row[colIndex]
            if (hasComparison && Array.isArray(value)) {
                return [value[0] != null ? String(value[0]) : '', value[1] != null ? String(value[1]) : '']
            }
            return value != null ? String(value) : ''
        })
    })

    return [displayHeaders, ...dataRows]
}

function copyWebAnalyticsTableToCsv(
    response: WebStatsTableQueryResponse,
    columns: string[],
    query: WebStatsTableQuery | WebGoalsQuery | WebExternalClicksTableQuery
): void {
    try {
        const tableData = getWebAnalyticsTableData(response, columns, query)
        const csv = Papa.unparse(tableData)
        void copyToClipboard(csv, 'table')
    } catch {
        lemonToast.error('Copy failed!')
    }
}

function copyWebAnalyticsTableToJson(
    response: WebStatsTableQueryResponse,
    columns: string[],
    query: WebStatsTableQuery | WebGoalsQuery | WebExternalClicksTableQuery
): void {
    try {
        const tableData = getWebAnalyticsTableData(response, columns, query)
        const headers = tableData[0]
        const rows = tableData.slice(1)

        const jsonData = rows.map((row) => {
            return headers.reduce(
                (acc, header, index) => {
                    acc[header] = row[index]
                    return acc
                },
                {} as Record<string, any>
            )
        })

        const json = JSON.stringify(jsonData, null, 4)
        void copyToClipboard(json, 'table')
    } catch {
        lemonToast.error('Copy failed!')
    }
}

function copyWebAnalyticsTableToExcel(
    response: WebStatsTableQueryResponse,
    columns: string[],
    query: WebStatsTableQuery | WebGoalsQuery | WebExternalClicksTableQuery
): void {
    try {
        const tableData = getWebAnalyticsTableData(response, columns, query)
        const tsv = Papa.unparse(tableData, { delimiter: '\t' })
        void copyToClipboard(tsv, 'table')
    } catch {
        lemonToast.error('Copy failed!')
    }
}

function getWebTrendsTableData(response: WebTrendsQueryResponse, query: WebTrendsQuery): string[][] {
    if (!response.results || response.results.length === 0) {
        return []
    }

    const hasComparison = query.compareFilter?.compare === true

    const allMetricsSet = new Set<WebTrendsMetric>()
    response.results.forEach((item) => {
        Object.keys(item.metrics).forEach((metric) => allMetricsSet.add(metric as WebTrendsMetric))
    })

    const orderedMetrics = Array.from(allMetricsSet).sort()

    if (orderedMetrics.length === 0) {
        return []
    }

    const displayHeaders = hasComparison
        ? [
              'Date',
              ...orderedMetrics.flatMap((m) => [
                  `${webTrendsMetricDisplayNames[m] || m} (current)`,
                  `${webTrendsMetricDisplayNames[m] || m} (previous)`,
              ]),
          ]
        : ['Date', ...orderedMetrics.map((m) => webTrendsMetricDisplayNames[m] || m)]

    const dataRows = response.results.map((item) => {
        const metricValues = orderedMetrics.flatMap((metric) => {
            const value = item.metrics[metric]
            if (hasComparison && Array.isArray(value)) {
                return [value[0] != null ? String(value[0]) : '', value[1] != null ? String(value[1]) : '']
            }
            return value != null ? String(value) : ''
        })
        return [item.bucket, ...metricValues]
    })

    return [displayHeaders, ...dataRows]
}

function copyWebTrendsToCsv(response: WebTrendsQueryResponse, query: WebTrendsQuery): void {
    try {
        const tableData = getWebTrendsTableData(response, query)
        const csv = Papa.unparse(tableData)
        void copyToClipboard(csv, 'table')
    } catch {
        lemonToast.error('Copy failed!')
    }
}

function copyWebTrendsToJson(response: WebTrendsQueryResponse, query: WebTrendsQuery): void {
    try {
        const tableData = getWebTrendsTableData(response, query)
        const headers = tableData[0]
        const rows = tableData.slice(1)

        const jsonData = rows.map((row) => {
            return headers.reduce(
                (acc, header, index) => {
                    acc[header] = row[index]
                    return acc
                },
                {} as Record<string, any>
            )
        })

        const json = JSON.stringify(jsonData, null, 4)
        void copyToClipboard(json, 'table')
    } catch {
        lemonToast.error('Copy failed!')
    }
}

function copyWebTrendsToExcel(response: WebTrendsQueryResponse, query: WebTrendsQuery): void {
    try {
        const tableData = getWebTrendsTableData(response, query)
        const tsv = Papa.unparse(tableData, { delimiter: '\t' })
        void copyToClipboard(tsv, 'table')
    } catch {
        lemonToast.error('Copy failed!')
    }
}

export function WebAnalyticsExport({ query, insightProps }: WebAnalyticsExportProps): JSX.Element | null {
    const builtInsightDataLogic = insightDataLogic(insightProps)
    const { insightDataRaw } = useValues(builtInsightDataLogic)

    const isTableQuery = query.kind === NodeKind.DataTableNode
    const isInsightVizQuery =
        query.kind === NodeKind.InsightVizNode && isWebTrendsQuery((query as InsightVizNode).source)

    if (!isTableQuery && !isInsightVizQuery) {
        return null
    }

    if (!insightDataRaw) {
        return null
    }

    let hasData = false
    if (isTableQuery) {
        const tableResponse = insightDataRaw as WebStatsTableQueryResponse
        hasData = tableResponse.results && tableResponse.results.length > 0
    } else if (isInsightVizQuery) {
        const trendsResponse = insightDataRaw as WebTrendsQueryResponse
        hasData = trendsResponse.results && trendsResponse.results.length > 0
    }

    if (!hasData) {
        return null
    }

    const handleCopy = (format: ExporterFormat): void => {
        if (isTableQuery) {
            const tableResponse = insightDataRaw as WebStatsTableQueryResponse
            const columns = (tableResponse.columns as string[]) || []
            const dataTableQuery = query as DataTableNode
            const source = dataTableQuery.source

            if (!columns.length) {
                return
            }

            const isWebAnalyticsTable =
                isWebStatsTableQuery(source) || isWebGoalsQuery(source) || isWebExternalClicksQuery(source)

            if (isWebAnalyticsTable) {
                const webAnalyticsSource = source as WebStatsTableQuery | WebGoalsQuery | WebExternalClicksTableQuery

                switch (format) {
                    case ExporterFormat.CSV:
                        copyWebAnalyticsTableToCsv(tableResponse, columns, webAnalyticsSource)
                        break
                    case ExporterFormat.JSON:
                        copyWebAnalyticsTableToJson(tableResponse, columns, webAnalyticsSource)
                        break
                    case ExporterFormat.XLSX:
                        copyWebAnalyticsTableToExcel(tableResponse, columns, webAnalyticsSource)
                        break
                }
            } else {
                const dataTableRows: DataTableRow[] = tableResponse.results.map((result) => ({
                    result: result as Record<string, any> | any[],
                }))

                if (!dataTableRows.length) {
                    return
                }

                switch (format) {
                    case ExporterFormat.CSV:
                        copyTableToCsv(dataTableRows, columns, dataTableQuery, columns)
                        break
                    case ExporterFormat.JSON:
                        copyTableToJson(dataTableRows, columns, dataTableQuery)
                        break
                    case ExporterFormat.XLSX:
                        copyTableToExcel(dataTableRows, columns, dataTableQuery, columns)
                        break
                }
            }
        } else if (isInsightVizQuery) {
            const trendsResponse = insightDataRaw as WebTrendsQueryResponse
            const insightVizNode = query as InsightVizNode
            const trendsQuery = insightVizNode.source

            if (!isWebTrendsQuery(trendsQuery)) {
                return
            }

            switch (format) {
                case ExporterFormat.CSV:
                    copyWebTrendsToCsv(trendsResponse, trendsQuery)
                    break
                case ExporterFormat.JSON:
                    copyWebTrendsToJson(trendsResponse, trendsQuery)
                    break
                case ExporterFormat.XLSX:
                    copyWebTrendsToExcel(trendsResponse, trendsQuery)
                    break
            }
        }
    }

    return (
        <LemonMenu
            items={[
                {
                    label: 'CSV',
                    onClick: () => handleCopy(ExporterFormat.CSV),
                },
                {
                    label: 'JSON',
                    onClick: () => handleCopy(ExporterFormat.JSON),
                },
                {
                    label: 'Excel',
                    onClick: () => handleCopy(ExporterFormat.XLSX),
                },
            ]}
            placement="bottom-end"
        >
            <LemonButton type="secondary" icon={<IconCopy />} size="small" data-attr="web-analytics-copy-dropdown">
                Copy
            </LemonButton>
        </LemonMenu>
    )
}
