import type { QueryEstimateResponseApi } from '../generated/api.schemas'
import { formatBytes } from '../scenes/WarehouseConsole/warehouseConsoleFormat'

export type EstimateWarningTone = 'danger' | 'warning' | 'muted'

export interface EstimateWarning {
    kind: 'exceeds_cap' | 'no_filter' | 'size_unknown'
    text: string
    tone: EstimateWarningTone
}

export function formatEstimateCost(usd: string | null): string | null {
    if (usd === null) {
        return null
    }
    const value = Number(usd)
    if (!Number.isFinite(value)) {
        return null
    }
    return value > 0 && value < 0.01 ? 'est. < $0.01' : `est. $${value.toFixed(2)}`
}

/** One line for the toolbar, for example "Scans up to 120 GiB · est. $0.29". */
export function estimateSummary(estimate: QueryEstimateResponseApi): string {
    if (estimate.upper_bound_bytes === null) {
        return 'Scan size unknown'
    }
    const cost = formatEstimateCost(estimate.estimated_cost_usd)
    return [`Scans up to ${formatBytes(estimate.upper_bound_bytes)}`, cost].filter(Boolean).join(' · ')
}

export function estimateBytesBucket(bytes: number | null): string {
    if (bytes === null) {
        return 'unknown'
    }
    const gib = bytes / 1024 ** 3
    return gib < 1 ? 'under_1_gib' : gib < 10 ? '1_to_10_gib' : gib < 100 ? '10_to_100_gib' : 'over_100_gib'
}

export function estimateWarnings(estimate: QueryEstimateResponseApi): EstimateWarning[] {
    const warnings: EstimateWarning[] = []
    if (estimate.warnings.includes('exceeds_cap') && estimate.cap_bytes !== null) {
        warnings.push({
            kind: 'exceeds_cap',
            text: `Over your ${formatBytes(estimate.cap_bytes)} per-query limit. This query will be stopped.`,
            tone: 'danger',
        })
    }
    if (estimate.warnings.includes('no_filter_on_large_table')) {
        const unfiltered = estimate.tables
            .filter((table) => !table.has_filter && table.size_bytes !== null)
            .sort((a, b) => (b.size_bytes ?? 0) - (a.size_bytes ?? 0))[0]
        if (unfiltered) {
            warnings.push({
                kind: 'no_filter',
                text: `No filter on ${unfiltered.table} (${formatBytes(unfiltered.size_bytes ?? 0)}). Add a time filter to scan less.`,
                tone: 'warning',
            })
        }
    }
    if (estimate.warnings.includes('size_unknown')) {
        const unknown = estimate.tables.filter((table) => table.size_bytes === null).length
        warnings.push({
            kind: 'size_unknown',
            text: unknown === 1 ? 'Size unknown for 1 table' : `Size unknown for ${unknown} tables`,
            tone: 'muted',
        })
    }
    return warnings
}
