import { AnalyticsQueryResponseBase, DataWarehouseSyncWarning } from '~/queries/schema/schema-general'
import { DashboardTile, InsightShortId } from '~/types'

export interface WarehouseSyncDashboardInsight {
    tileId: number
    shortId: InsightShortId
    name: string
}

export interface WarehouseSyncDashboardEntry {
    warning: DataWarehouseSyncWarning
    insights: WarehouseSyncDashboardInsight[]
}

// The backend `message` on a DataWarehouseSyncWarning is kept self-contained (it also feeds
// LLM/MCP contexts), so it restates "results may be out of date" — which the sync-warning banner
// header already says. Strip that redundant tail for display only, while preserving any
// "a new sync is in progress" detail. Messages without that tail (failed, paused) are left as-is.
export const trimRedundantTail = (message: string): string =>
    message
        .replace(/\.\s*(A new sync is in progress) but results may be out of date\.?\s*$/i, '. $1.')
        .replace(/\.\s*Results may be out of date\.?\s*$/i, '.')

export function warehouseSyncWarnings(
    warnings: AnalyticsQueryResponseBase['warnings'] | null | undefined
): DataWarehouseSyncWarning[] {
    return (warnings ?? []).filter((warning): warning is DataWarehouseSyncWarning => warning.type === 'warehouse_sync')
}

/** One entry per out-of-date table on the dashboard, with every insight that reads it. */
export function warehouseSyncDashboardEntries(tiles: DashboardTile[]): WarehouseSyncDashboardEntry[] {
    const entries = new Map<string, WarehouseSyncDashboardEntry>()
    for (const tile of tiles) {
        const insight = tile.insight
        if (!insight || insight.deleted) {
            continue
        }
        for (const warning of warehouseSyncWarnings(insight.warnings)) {
            const key = `${warning.source_id ?? warning.source_type}:${warning.schema_name}:${warning.table_name}`
            const entry = entries.get(key) ?? { warning, insights: [] }
            entry.insights.push({
                tileId: tile.id,
                shortId: insight.short_id,
                name: insight.name || insight.derived_name || 'Untitled',
            })
            entries.set(key, entry)
        }
    }
    return [...entries.values()]
}
