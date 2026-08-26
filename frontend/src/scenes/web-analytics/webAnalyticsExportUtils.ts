import { strToU8, zipSync } from 'fflate'

import { lemonToast } from '@posthog/lemon-ui'

import { downloadFile } from 'lib/utils/dom'
import { slugify } from 'lib/utils/strings'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'

import { ExportAdapter, csvFromTableData, getInsightExportAdapter } from '~/queries/nodes/InsightViz/exportAdapters'
import {
    DataTableNode,
    NodeKind,
    QuerySchema,
    WebExternalClicksTableQuery,
    WebGoalsQuery,
    WebStatsTableQuery,
    WebStatsTableQueryResponse,
} from '~/queries/schema/schema-general'
import { isWebExternalClicksQuery, isWebGoalsQuery, isWebStatsTableQuery } from '~/queries/utils'
import { TabsTileTab, TILE_LABELS, WebAnalyticsTile, getDisplayColumnName } from '~/scenes/web-analytics/common'
import { InsightLogicProps } from '~/types'

export interface TileExportSection {
    title: string
    tableData: string[][]
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
    const webAdapter = new WebAnalyticsTableAdapter(insightDataRaw as WebStatsTableQueryResponse, query)
    if (webAdapter.canHandle()) {
        return webAdapter
    }
    return getInsightExportAdapter(insightDataRaw, query)
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

export class WebAnalyticsTableAdapter implements ExportAdapter {
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
