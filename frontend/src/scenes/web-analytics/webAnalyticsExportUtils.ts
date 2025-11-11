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
} from '~/queries/schema/schema-general'
import { isTrendsQuery, isWebExternalClicksQuery, isWebGoalsQuery, isWebStatsTableQuery } from '~/queries/utils'
import { getDisplayColumnName } from '~/scenes/web-analytics/common'
import { ChartDisplayType, ExporterFormat } from '~/types'

export interface ExportAdapter {
    toTableData(): string[][]
    canHandle(): boolean
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

class CalendarHeatmapAdapter implements ExportAdapter {
    constructor(
        private response: TrendsQueryResponse,
        private query?: QuerySchema
    ) {}

    private getCalendarHeatmapTableData(rowLabels: string[], columnLabels: string[]): string[][] {
        const firstResult = (this.response as any)?.results?.[0]
        const heatmapData = firstResult?.calendar_heatmap_data

        if (!heatmapData || !heatmapData.data) {
            return []
        }

        const data = heatmapData.data
        const rowAggregations = heatmapData.rowAggregations || []
        const columnAggregations = heatmapData.columnAggregations || []
        const allAggregations = heatmapData.allAggregations || 0

        const numRows = rowLabels.length
        const numCols = columnLabels.length

        const matrix: number[][] = Array(numRows)
            .fill(0)
            .map(() => Array(numCols).fill(0))
        data.forEach((item: EventsHeatMapDataResult) => {
            if (item.row < numRows && item.column < numCols) {
                matrix[item.row][item.column] = item.value
            }
        })

        const rowAggMap: Record<number, number> = {}
        rowAggregations.forEach((item: EventsHeatMapRowAggregationResult) => {
            rowAggMap[item.row] = item.value
        })

        const colAggArray: number[] = Array(numCols).fill(0)
        columnAggregations.forEach((item: EventsHeatMapColumnAggregationResult) => {
            if (item.column < numCols) {
                colAggArray[item.column] = item.value
            }
        })

        const headers = ['', ...columnLabels, 'All']
        const dataRows = rowLabels.map((rowLabel, rowIndex) => {
            const rowValues = matrix[rowIndex].map(String)
            const rowTotal = rowAggMap[rowIndex] != null ? String(rowAggMap[rowIndex]) : ''
            return [rowLabel, ...rowValues, rowTotal]
        })

        const aggregationRow = ['All', ...colAggArray.map(String), String(allAggregations)]

        return [headers, ...dataRows, aggregationRow]
    }

    toTableData(): string[][] {
        const dayLabels = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
        const hourLabels = Array.from({ length: 24 }, (_, i) => String(i))
        return this.getCalendarHeatmapTableData(dayLabels, hourLabels)
    }

    canHandle(): boolean {
        if (!this.query || this.query.kind !== NodeKind.InsightVizNode) {
            return false
        }
        const source = (this.query as InsightVizNode).source
        if (!isTrendsQuery(source)) {
            return false
        }
        const isHeatmap = (source as TrendsQuery)?.trendsFilter?.display === ChartDisplayType.CalendarHeatmap
        if (!isHeatmap) {
            return false
        }

        const firstResult = (this.response as any)?.results?.[0]
        const heatmapData = firstResult?.calendar_heatmap_data
        return heatmapData && heatmapData.data && heatmapData.data.length > 0
    }
}

class WebAnalyticsTableAdapter implements ExportAdapter {
    constructor(
        private response: WebStatsTableQueryResponse,
        private query?: QuerySchema
    ) {}

    private getWebAnalyticsTableData(
        columns: string[],
        source: WebStatsTableQuery | WebGoalsQuery | WebExternalClicksTableQuery
    ): string[][] {
        if (!this.response.results || this.response.results.length === 0 || !columns.length) {
            return []
        }

        const hasComparison = source.compareFilter?.compare === true
        const breakdownBy = isWebStatsTableQuery(source) ? source.breakdownBy : undefined

        const firstRow = this.response.results[0] as any[]
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

        const dataRows = this.response.results.map((result) => {
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

    toTableData(): string[][] {
        if (!this.query) {
            return []
        }
        const dataTableQuery = this.query as DataTableNode
        const source = dataTableQuery.source as WebStatsTableQuery | WebGoalsQuery | WebExternalClicksTableQuery
        const columns = (this.response.columns as string[]) || []
        return this.getWebAnalyticsTableData(columns, source)
    }

    canHandle(): boolean {
        if (!this.query || this.query.kind !== NodeKind.DataTableNode) {
            return false
        }
        const dataTableQuery = this.query as DataTableNode
        const source = dataTableQuery.source
        const isWebAnalytics =
            isWebStatsTableQuery(source) || isWebGoalsQuery(source) || isWebExternalClicksQuery(source)

        if (!isWebAnalytics) {
            return false
        }

        const hasData = this.response.results && this.response.results.length > 0
        const columns = (this.response.columns as string[]) || []

        return hasData && columns.length > 0
    }
}

class WorldMapAdapter implements ExportAdapter {
    constructor(
        private response: TrendsQueryResponse,
        private query?: QuerySchema
    ) {}

    private getWorldMapTableData(): string[][] {
        if (!this.response.results || this.response.results.length === 0) {
            return []
        }

        const headers = ['Country', 'Visitors']
        const dataRows = this.response.results.map((series) => {
            const countryCode = series.label ?? ''
            const visitors = (series as any).aggregated_value ?? series.count ?? 0
            return [countryCode, String(visitors)]
        })

        return [headers, ...dataRows]
    }

    toTableData(): string[][] {
        return this.getWorldMapTableData()
    }

    canHandle(): boolean {
        if (!this.query || this.query.kind !== NodeKind.InsightVizNode) {
            return false
        }
        const source = (this.query as InsightVizNode).source
        if (!isTrendsQuery(source)) {
            return false
        }

        const isWorldMap = (source as TrendsQuery)?.trendsFilter?.display === ChartDisplayType.WorldMap
        if (!isWorldMap) {
            return false
        }

        return this.response.results && this.response.results.length > 0
    }
}

class TrendsAdapter implements ExportAdapter {
    constructor(
        private response: TrendsQueryResponse,
        private query?: QuerySchema
    ) {}

    private getTrendsTableData(): string[][] {
        if (!this.response.results || this.response.results.length === 0) {
            return []
        }

        // Get date labels from the first series (all series should have the same labels)
        const firstSeries = this.response.results[0]
        const dateLabels = (firstSeries.labels || firstSeries.days || []) as string[]

        if (dateLabels.length === 0) {
            return []
        }

        const seriesLabels = this.response.results.map((series) => {
            // Use breakdown value if available, otherwise use action name or label
            const breakdownValue = (series as any).breakdown_value
            const baseName = breakdownValue ?? series.action?.custom_name ?? series.label ?? 'Series'
            const compareLabel = series.compare_label
            return compareLabel ? `${baseName} (${compareLabel})` : baseName
        })
        const headers = ['Date', ...seriesLabels]

        const dataRows = dateLabels.map((date, dateIndex) => {
            const values = this.response.results.map((series) => {
                const data = series.data as number[]
                const value = data[dateIndex]
                return value != null ? String(value) : ''
            })
            return [date, ...values]
        })

        return [headers, ...dataRows]
    }

    toTableData(): string[][] {
        return this.getTrendsTableData()
    }

    canHandle(): boolean {
        if (!this.query || this.query.kind !== NodeKind.InsightVizNode) {
            return false
        }
        const source = (this.query as InsightVizNode).source
        if (!isTrendsQuery(source)) {
            return false
        }

        // Exclude calendar heatmaps and world maps (handled by their own adapters)
        const display = (source as TrendsQuery)?.trendsFilter?.display
        if (display === ChartDisplayType.CalendarHeatmap || display === ChartDisplayType.WorldMap) {
            return false
        }

        return this.response.results && this.response.results.length > 0
    }
}

export { CalendarHeatmapAdapter, WorldMapAdapter, WebAnalyticsTableAdapter, TrendsAdapter }
