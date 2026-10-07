import { hashCodeForString } from 'lib/utils/strings'

import { AnalyticsQueryResponseBase, DataWarehouseSyncWarning } from '~/queries/schema/schema-general'
import { DashboardTile } from '~/types'

export interface WarehouseSyncDashboardSource {
    sourceType: string
    /** Null when the warning names no source to link to. */
    sourceId: string | null
}

export interface WarehouseSyncDashboardSummary {
    sources: WarehouseSyncDashboardSource[]
    insightCount: number
    /**
     * Identifies the set of out-of-date tables and their statuses. It ignores the message, whose
     * "3 days ago" text changes on every recompute.
     */
    fingerprint: string
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

/**
 * The sync warnings whose data is behind its sync schedule. A sync paused recently still serves current
 * data, so a surface that says "out of date" leaves that warning out.
 */
export function outOfDateSyncWarnings(
    warnings: AnalyticsQueryResponseBase['warnings'] | null | undefined
): DataWarehouseSyncWarning[] {
    return warehouseSyncWarnings(warnings).filter((warning) => !warning.data_is_current)
}

/** The out-of-date warehouse sources behind a dashboard's insights, or null when every insight is current. */
export function warehouseSyncDashboardSummary(tiles: DashboardTile[]): WarehouseSyncDashboardSummary | null {
    const sources = new Map<string, WarehouseSyncDashboardSource>()
    const tables = new Set<string>()
    let insightCount = 0
    for (const tile of tiles) {
        const insight = tile.insight
        if (!insight || insight.deleted) {
            continue
        }
        const warnings = outOfDateSyncWarnings(insight.warnings)
        if (warnings.length === 0) {
            continue
        }
        insightCount += 1
        for (const warning of warnings) {
            const sourceKey = warning.source_id ?? warning.source_type
            sources.set(sourceKey, { sourceType: warning.source_type, sourceId: warning.source_id ?? null })
            tables.add(`${sourceKey}:${warning.schema_name}:${warning.table_name}:${warning.status}`)
        }
    }
    if (insightCount === 0) {
        return null
    }
    return {
        sources: [...sources.values()],
        insightCount,
        fingerprint: String(hashCodeForString([...tables].sort().join('|'))),
    }
}
