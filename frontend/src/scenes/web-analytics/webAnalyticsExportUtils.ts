import { strToU8, zipSync } from 'fflate'
import Papa from 'papaparse'

import { lemonToast } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { downloadFile } from 'lib/utils/dom'
import { slugify } from 'lib/utils/strings'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'

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
import { TabsTileTab, TILE_LABELS, WebAnalyticsTile, getDisplayColumnName } from '~/scenes/web-analytics/common'
import { ChartDisplayType, ExporterFormat, InsightLogicProps } from '~/types'

export interface ExportAdapter {
    toTableData(): string[][]
    canHandle(): boolean
}

export interface TileExportSection {
    title: string
    tableData: string[][]
}

export function csvFromTableData(tableData: string[][]): string {
    return Papa.unparse(tableData, { escapeFormulae: true })
}

export function downloadTableDataAsCsv(tableData: string[][], filename: string): boolean {
    if (tableData.length === 0) {
        lemonToast.warning('No data to export yet')
        return false
    }
    try {
        const file = new File([csvFromTableData(tableData)], filename, { type: 'text/csv' })
        downloadFile(file)
        return true
    } catch {
        lemonToast.error('Export failed')
        return false
    }
}

function slugifyTileTitle(title: string): string {
    return slugify(title) || 'tile'
}

export function buildCsvFilenames(titles: string[]): string[] {
    const seen = new Map<string, number>()
    return titles.map((title) => {
        const stem = slugifyTileTitle(title)
        const count = seen.get(stem) ?? 0
        seen.set(stem, count + 1)
        return count === 0 ? `${stem}.csv` : `${stem}-${count + 1}.csv`
    })
}

export function downloadTilesAsCsvZip(sections: TileExportSection[], filename: string): boolean {
    try {
        const populated = sections.filter((section) => section.tableData.length > 0)
        const filenames = buildCsvFilenames(populated.map((section) => section.title))
        const entries: Record<string, Uint8Array> = {}
        populated.forEach((section, index) => {
            entries[filenames[index]] = strToU8(csvFromTableData(section.tableData))
        })
        const zipped = zipSync(entries)
        downloadFile(new File([zipped as BlobPart], filename, { type: 'application/zip' }))
        return true
    } catch {
        lemonToast.error('Export failed')
        return false
    }
}

export function getExportAdapter(insightDataRaw: unknown, query: QuerySchema | undefined): ExportAdapter | null {
    if (!insightDataRaw || !query) {
        return null
    }
    const adapters: ExportAdapter[] = [
        new CalendarHeatmapAdapter(insightDataRaw as TrendsQueryResponse, query),
        new WorldMapAdapter(insightDataRaw as TrendsQueryResponse, query),
        new WebAnalyticsTableAdapter(insightDataRaw as WebStatsTableQueryResponse, query),
        new TrendsAdapter(insightDataRaw as TrendsQueryResponse, query),
    ]
    return adapters.find((a) => a.canHandle()) ?? null
}

function tileToTableData(query: QuerySchema, insightProps: InsightLogicProps): string[][] | null {
    const insightDataRaw = insightDataLogic.findMounted(insightProps)?.values.insightDataRaw
    const adapter = getExportAdapter(insightDataRaw, query)
    const tableData = adapter?.toTableData() ?? []
    return tableData.length > 0 ? tableData : null
}

function isTileStillLoading(insightProps: InsightLogicProps): boolean {
    return insightDataLogic.findMounted(insightProps)?.values.insightDataLoading === true
}

export function anyTileStillLoading(tiles: WebAnalyticsTile[]): boolean {
    for (const tile of tiles) {
        if (tile.kind === 'query') {
            if (isTileStillLoading(tile.insightProps)) {
                return true
            }
        } else if (tile.kind === 'tabs') {
            const activeTab = tile.tabs.find((tab) => tab.id === tile.activeTabId)
            if (activeTab && isTileStillLoading(activeTab.insightProps)) {
                return true
            }
        } else if (tile.kind === 'section') {
            if (anyTileStillLoading(tile.tiles)) {
                return true
            }
        }
    }
    return false
}

function tabSectionTitle(tile: { tileId: WebAnalyticsTile['tileId'] }, tab: TabsTileTab): string {
    const base = TILE_LABELS[tile.tileId]
    const tabTitle =
        typeof tab.title === 'string' ? tab.title : typeof tab.linkText === 'string' ? tab.linkText : tab.id
    return base ? `${base}: ${tabTitle}` : tabTitle
}

export function exportAllTilesAsCsvZip(tiles: WebAnalyticsTile[], filename = 'web-analytics-export.zip'): boolean {
    const sections = collectAllTilesTableData(tiles)
    if (sections.length === 0) {
        lemonToast.warning('No data to export yet')
        return false
    }
    if (!downloadTilesAsCsvZip(sections, filename)) {
        return false
    }
    if (anyTileStillLoading(tiles)) {
        lemonToast.warning('Some tiles are still loading, so this export may be incomplete')
    }
    return true
}

export function collectAllTilesTableData(tiles: WebAnalyticsTile[]): TileExportSection[] {
    const sections: TileExportSection[] = []
    for (const tile of tiles) {
        if (tile.kind === 'query') {
            const tableData = tileToTableData(tile.query, tile.insightProps)
            if (tableData) {
                sections.push({ title: tile.title ?? TILE_LABELS[tile.tileId] ?? tile.tileId, tableData })
            }
        } else if (tile.kind === 'tabs') {
            const activeTab = tile.tabs.find((tab) => tab.id === tile.activeTabId)
            if (activeTab) {
                const tableData = tileToTableData(activeTab.query, activeTab.insightProps)
                if (tableData) {
                    sections.push({ title: tabSectionTitle(tile, activeTab), tableData })
                }
            }
        } else if (tile.kind === 'section') {
            sections.push(...collectAllTilesTableData(tile.tiles))
        }
    }
    return sections
}

export function exportTableData(tableData: string[][], format: ExporterFormat): void {
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

function convertClickHouseDayToStandard(clickHouseDay: number): number {
    // ClickHouse toDayOfWeek: 1=Mon, 2=Tue, ..., 7=Sun
    // Standard array indices: 0=Sun, 1=Mon, ..., 6=Sat
    return clickHouseDay % 7
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

class WebAnalyticsTableAdapter implements ExportAdapter {
    constructor(
        private response: WebStatsTableQueryResponse,
        private query?: QuerySchema
    ) {}

    private getWebAnalyticsTableData(
        columns: string[],
        source: WebStatsTableQuery | WebGoalsQuery | WebExternalClicksTableQuery,
        keptIndices: number[]
    ): string[][] {
        if (!this.response.results || this.response.results.length === 0 || !columns.length) {
            return []
        }

        const hasComparison = source.compareFilter?.compare === true
        const breakdownBy = isWebStatsTableQuery(source) ? source.breakdownBy : undefined

        const firstRow = this.response.results[0] as any[]
        const columnHasComparison = columns.map((_, colIndex) => Array.isArray(firstRow[keptIndices[colIndex]]))

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
                const value = row[keptIndices[colIndex]]
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
        const allColumns = (this.response.columns as string[]) || []

        // Filter out internal UI state columns that shouldn't be exported
        const columnsToKeep = allColumns
            .map((col, index) => ({ col, index }))
            .filter(({ col }) => !col.includes('ui_fill_fraction') && !col.includes('cross_sell'))

        const filteredColumns = columnsToKeep.map(({ col }) => col)
        const keptIndices = columnsToKeep.map(({ index }) => index)

        return this.getWebAnalyticsTableData(filteredColumns, source, keptIndices)
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
