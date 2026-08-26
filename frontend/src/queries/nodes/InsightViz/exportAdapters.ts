import Papa from 'papaparse'

import { lemonToast } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import {
    EventsHeatMapColumnAggregationResult,
    EventsHeatMapDataResult,
    EventsHeatMapRowAggregationResult,
    InsightVizNode,
    Node,
    NodeKind,
    QuerySchema,
    TrendsQuery,
    TrendsQueryResponse,
} from '~/queries/schema/schema-general'
import { isTrendsQuery } from '~/queries/utils'
import { ChartDisplayType, ExporterFormat } from '~/types'

export interface ExportAdapter {
    toTableData(): string[][]
    canHandle(): boolean
}

export function csvFromTableData(tableData: string[][]): string {
    return Papa.unparse(tableData, { escapeFormulae: true })
}

export function copyTableData(tableData: string[][], format: ExporterFormat): void {
    if (tableData.length === 0) {
        lemonToast.warning('No data to copy yet')
        return
    }
    try {
        switch (format) {
            case ExporterFormat.CSV: {
                const csv = csvFromTableData(tableData)
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
                const tsv = Papa.unparse(tableData, { delimiter: '\t', escapeFormulae: true })
                void copyToClipboard(tsv, 'table')
                break
            }
        }
    } catch {
        lemonToast.error('Copy failed!')
    }
}

/**
 * Returns an adapter that converts a loaded insight response into tabular data, or null when the
 * insight kind isn't supported or no data is loaded yet.
 */
export function getInsightExportAdapter(insightDataRaw: unknown, query: Node | null | undefined): ExportAdapter | null {
    if (!insightDataRaw || !query) {
        return null
    }
    const raw = insightDataRaw as Record<string, any>
    // Cached insight models (dashboard tiles that haven't refreshed this session) carry the series
    // under the legacy `result` key, while fresh query responses use `results`.
    const response = (
        raw.results == null && Array.isArray(raw.result) ? { ...raw, results: raw.result } : raw
    ) as TrendsQueryResponse
    const adapters: ExportAdapter[] = [
        new CalendarHeatmapAdapter(response, query as QuerySchema),
        new WorldMapAdapter(response, query as QuerySchema),
        new TrendsAdapter(response, query as QuerySchema),
    ]
    return adapters.find((a) => a.canHandle()) ?? null
}

function convertClickHouseDayToStandard(clickHouseDay: number): number {
    // ClickHouse toDayOfWeek: 1=Mon, 2=Tue, ..., 7=Sun
    // Standard array indices: 0=Sun, 1=Mon, ..., 6=Sat
    return clickHouseDay % 7
}

export class CalendarHeatmapAdapter implements ExportAdapter {
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
            const standardDay = convertClickHouseDayToStandard(item.row)
            if (standardDay < numRows && item.column < numCols) {
                matrix[standardDay][item.column] = item.value
            }
        })

        const rowAggMap: Record<number, number> = {}
        rowAggregations.forEach((item: EventsHeatMapRowAggregationResult) => {
            const standardDay = convertClickHouseDayToStandard(item.row)
            rowAggMap[standardDay] = item.value
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

export class WorldMapAdapter implements ExportAdapter {
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

export class TrendsAdapter implements ExportAdapter {
    constructor(
        private response: TrendsQueryResponse,
        private query?: QuerySchema
    ) {}

    private getSeriesLabel(series: Record<string, any>): string {
        // Use breakdown value if available, otherwise use action name or label
        const breakdownValue = series.breakdown_value
        const baseName = breakdownValue ?? series.action?.custom_name ?? series.label ?? 'Series'
        const compareLabel = series.compare_label
        return compareLabel ? `${baseName} (${compareLabel})` : String(baseName)
    }

    // Value-aggregated displays (bold number, pie, total value bar) return a single number per
    // series and no date axis, so the table is one row per series instead of one row per date.
    private getAggregateTableData(): string[][] {
        const rows = this.response.results
            .filter((series) => (series as any).aggregated_value != null || series.count != null)
            .map((series) => [this.getSeriesLabel(series), String((series as any).aggregated_value ?? series.count)])

        return rows.length > 0 ? [['Series', 'Total value'], ...rows] : []
    }

    private getTrendsTableData(): string[][] {
        if (!this.response.results || this.response.results.length === 0) {
            return []
        }

        // Get date labels from the first series (all series should have the same labels)
        const firstSeries = this.response.results[0]
        const dateLabels = (firstSeries.labels || firstSeries.days || []) as string[]

        if (dateLabels.length === 0) {
            return this.getAggregateTableData()
        }

        const seriesLabels = this.response.results.map((series) => this.getSeriesLabel(series))
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
