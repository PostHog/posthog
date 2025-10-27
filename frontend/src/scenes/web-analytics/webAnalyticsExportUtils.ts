import Papa from 'papaparse'

import { lemonToast } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import {
    DataTableNode,
    EventsHeatMapColumnAggregationResult,
    EventsHeatMapDataResult,
    EventsHeatMapRowAggregationResult,
    InsightVizNode,
    NodeKind,
    QuerySchema,
    TrendsQuery,
    TrendsQueryResponse,
    WebExternalClicksTableQuery,
    WebGoalsQuery,
    WebStatsTableQuery,
    WebStatsTableQueryResponse,
    WebTrendsMetric,
    WebTrendsQuery,
    WebTrendsQueryResponse,
} from '~/queries/schema/schema-general'
import {
    isTrendsQuery,
    isWebExternalClicksQuery,
    isWebGoalsQuery,
    isWebStatsTableQuery,
    isWebTrendsQuery,
} from '~/queries/utils'
import { getDisplayColumnName } from '~/scenes/web-analytics/tiles/WebAnalyticsTile'
import { ChartDisplayType, ExporterFormat } from '~/types'

export const webTrendsMetricDisplayNames: Record<WebTrendsMetric, string> = {
    [WebTrendsMetric.UNIQUE_USERS]: 'Visitors',
    [WebTrendsMetric.PAGE_VIEWS]: 'Views',
    [WebTrendsMetric.SESSIONS]: 'Sessions',
    [WebTrendsMetric.BOUNCES]: 'Bounces',
    [WebTrendsMetric.SESSION_DURATION]: 'Session duration',
    [WebTrendsMetric.TOTAL_SESSIONS]: 'Total sessions',
}

export interface ExportAdapter {
    toTableData(response: any, query: QuerySchema): string[][]
    canHandle(query: QuerySchema, response: any): boolean
}

export function exportTableData(tableData: string[][], format: ExporterFormat): void {
    try {
        switch (format) {
            case ExporterFormat.CSV: {
                const csv = Papa.unparse(tableData)
                void copyToClipboard(csv, 'table')
                break
            }
            case ExporterFormat.JSON: {
                const [headers, ...rows] = tableData
                const jsonData = rows.map((row) =>
                    headers.reduce(
                        (acc, header, index) => {
                            acc[header] = row[index]
                            return acc
                        },
                        {} as Record<string, any>
                    )
                )
                void copyToClipboard(JSON.stringify(jsonData, null, 4), 'table')
                break
            }
            case ExporterFormat.XLSX: {
                const tsv = Papa.unparse(tableData, { delimiter: '\t' })
                void copyToClipboard(tsv, 'table')
                break
            }
        }
    } catch {
        lemonToast.error('Copy failed!')
    }
}

export function getCalendarHeatmapTableData(
    response: TrendsQueryResponse,
    rowLabels: string[],
    columnLabels: string[]
): string[][] {
    const firstResult = (response as any)?.results?.[0]
    const heatmapData = firstResult?.calendar_heatmap_data

    if (!heatmapData || !heatmapData.data) {
        return []
    }

    const data = heatmapData.data || []
    const rowAggregations = heatmapData.rowAggregations || []
    const columnAggregations = heatmapData.columnAggregations || []
    const allAggregations = heatmapData.allAggregations || 0

    const numRows = rowLabels.length
    const numCols = columnLabels.length

    // Create matrix from sparse data
    const matrix: number[][] = Array(numRows)
        .fill(0)
        .map(() => Array(numCols).fill(0))
    data.forEach((item: EventsHeatMapDataResult) => {
        if (item.row < numRows && item.column < numCols) {
            matrix[item.row][item.column] = item.value
        }
    })

    // Create row aggregations map
    const rowAggMap: Record<number, number> = {}
    rowAggregations.forEach((item: EventsHeatMapRowAggregationResult) => {
        rowAggMap[item.row] = item.value
    })

    // Create column aggregations array
    const colAggArray: number[] = Array(numCols).fill(0)
    columnAggregations.forEach((item: EventsHeatMapColumnAggregationResult) => {
        if (item.column < numCols) {
            colAggArray[item.column] = item.value
        }
    })

    // Build table with headers
    const headers = ['', ...columnLabels, 'All']
    const dataRows = rowLabels.map((rowLabel, rowIndex) => {
        const rowValues = matrix[rowIndex].map(String)
        const rowTotal = rowAggMap[rowIndex] != null ? String(rowAggMap[rowIndex]) : ''
        return [rowLabel, ...rowValues, rowTotal]
    })

    const aggregationRow = ['All', ...colAggArray.map(String), String(allAggregations)]

    return [headers, ...dataRows, aggregationRow]
}

class CalendarHeatmapAdapter implements ExportAdapter {
    toTableData(response: TrendsQueryResponse): string[][] {
        const dayLabels = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
        const hourLabels = Array.from({ length: 24 }, (_, i) => String(i))
        return getCalendarHeatmapTableData(response, dayLabels, hourLabels)
    }

    canHandle(query: QuerySchema, response: any): boolean {
        if (query.kind !== NodeKind.InsightVizNode) {
            return false
        }
        const source = (query as InsightVizNode).source
        if (!isTrendsQuery(source)) {
            return false
        }
        const isHeatmap = (source as TrendsQuery)?.trendsFilter?.display === ChartDisplayType.CalendarHeatmap
        if (!isHeatmap) {
            return false
        }

        const trendsResponse = response as TrendsQueryResponse
        const firstResult = (trendsResponse as any)?.results?.[0]
        const heatmapData = firstResult?.calendar_heatmap_data
        return heatmapData && heatmapData.data && heatmapData.data.length > 0
    }
}

export function getWebAnalyticsTableData(
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

class WebAnalyticsTableAdapter implements ExportAdapter {
    toTableData(response: WebStatsTableQueryResponse, query: QuerySchema): string[][] {
        const dataTableQuery = query as DataTableNode
        const source = dataTableQuery.source as WebStatsTableQuery | WebGoalsQuery | WebExternalClicksTableQuery
        const columns = (response.columns as string[]) || []
        return getWebAnalyticsTableData(response, columns, source)
    }

    canHandle(query: QuerySchema, response: any): boolean {
        if (query.kind !== NodeKind.DataTableNode) {
            return false
        }
        const dataTableQuery = query as DataTableNode
        const source = dataTableQuery.source
        const isWebAnalytics =
            isWebStatsTableQuery(source) || isWebGoalsQuery(source) || isWebExternalClicksQuery(source)

        if (!isWebAnalytics) {
            return false
        }

        const tableResponse = response as WebStatsTableQueryResponse
        const hasData = tableResponse.results && tableResponse.results.length > 0
        const columns = (tableResponse.columns as string[]) || []

        return hasData && columns.length > 0
    }
}

export function getWebTrendsTableData(response: WebTrendsQueryResponse, query: WebTrendsQuery): string[][] {
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

class WebTrendsAdapter implements ExportAdapter {
    toTableData(response: WebTrendsQueryResponse, query: QuerySchema): string[][] {
        const insightVizNode = query as InsightVizNode
        const source = insightVizNode.source as unknown as WebTrendsQuery
        return getWebTrendsTableData(response, source)
    }

    canHandle(query: QuerySchema, response: any): boolean {
        if (query.kind !== NodeKind.InsightVizNode) {
            return false
        }
        const source = (query as InsightVizNode).source
        if (!isWebTrendsQuery(source)) {
            return false
        }

        const trendsResponse = response as WebTrendsQueryResponse
        return trendsResponse.results && trendsResponse.results.length > 0
    }
}

export function getWorldMapTableData(response: TrendsQueryResponse): string[][] {
    if (!response.results || response.results.length === 0) {
        return []
    }

    // World Map shows breakdown by country with aggregated values
    const headers = ['Country', 'Visitors']
    const dataRows = response.results.map((series) => {
        const countryCode = series.label ?? ''
        const visitors = (series as any).aggregated_value ?? series.count ?? 0
        return [countryCode, String(visitors)]
    })

    return [headers, ...dataRows]
}

export function getTrendsTableData(response: TrendsQueryResponse): string[][] {
    if (!response.results || response.results.length === 0) {
        return []
    }

    // Get date labels from the first series (all series should have the same labels)
    const firstSeries = response.results[0]
    const dateLabels = (firstSeries.labels || firstSeries.days || []) as string[]

    if (dateLabels.length === 0) {
        return []
    }

    // Create headers: Date + each series label
    const seriesLabels = response.results.map((series) => {
        // Use breakdown value if available, otherwise use action name or label
        const breakdownValue = (series as any).breakdown_value
        const baseName = breakdownValue ?? series.action?.custom_name ?? series.label ?? 'Series'
        const compareLabel = series.compare_label
        return compareLabel ? `${baseName} (${compareLabel})` : baseName
    })
    const headers = ['Date', ...seriesLabels]

    // Create data rows: each row is a date with values from all series
    const dataRows = dateLabels.map((date, dateIndex) => {
        const values = response.results.map((series) => {
            const data = series.data as number[]
            const value = data[dateIndex]
            return value != null ? String(value) : ''
        })
        return [date, ...values]
    })

    return [headers, ...dataRows]
}

class WorldMapAdapter implements ExportAdapter {
    toTableData(response: TrendsQueryResponse): string[][] {
        return getWorldMapTableData(response)
    }

    canHandle(query: QuerySchema, response: any): boolean {
        if (query.kind !== NodeKind.InsightVizNode) {
            return false
        }
        const source = (query as InsightVizNode).source
        if (!isTrendsQuery(source)) {
            return false
        }

        // Check if it's a World Map display
        const isWorldMap = (source as TrendsQuery)?.trendsFilter?.display === ChartDisplayType.WorldMap
        if (!isWorldMap) {
            return false
        }

        const trendsResponse = response as TrendsQueryResponse
        return trendsResponse.results && trendsResponse.results.length > 0
    }
}

class TrendsAdapter implements ExportAdapter {
    toTableData(response: TrendsQueryResponse): string[][] {
        return getTrendsTableData(response)
    }

    canHandle(query: QuerySchema, response: any): boolean {
        if (query.kind !== NodeKind.InsightVizNode) {
            return false
        }
        const source = (query as InsightVizNode).source
        if (!isTrendsQuery(source)) {
            return false
        }

        // Exclude calendar heatmaps (handled by CalendarHeatmapAdapter)
        const isHeatmap = (source as TrendsQuery)?.trendsFilter?.display === ChartDisplayType.CalendarHeatmap
        if (isHeatmap) {
            return false
        }

        // Exclude world maps (handled by WorldMapAdapter)
        const isWorldMap = (source as TrendsQuery)?.trendsFilter?.display === ChartDisplayType.WorldMap
        if (isWorldMap) {
            return false
        }

        const trendsResponse = response as TrendsQueryResponse
        return trendsResponse.results && trendsResponse.results.length > 0
    }
}

export const adapters: ExportAdapter[] = [
    new CalendarHeatmapAdapter(),
    new WorldMapAdapter(),
    new WebAnalyticsTableAdapter(),
    new WebTrendsAdapter(),
    new TrendsAdapter(),
]
