import { humanFriendlyCurrency } from 'lib/utils/numbers'

import type { BillingProductV2Type } from '~/types'

// Tiered pricing and the free allowance apply to the organization total, so this is an average-price estimate.
export function estimateSourceCostsUsd(
    billableRowsBySource: Record<string, number>,
    syncedRowsProduct: Pick<BillingProductV2Type, 'current_amount_usd' | 'current_usage'> | null | undefined
): Record<string, number> | null {
    const amountUsd = parseFloat(syncedRowsProduct?.current_amount_usd ?? '')
    if (Number.isNaN(amountUsd)) {
        return null
    }
    const projectRows = Object.values(billableRowsBySource).reduce((sum, rows) => sum + rows, 0)
    // Billing counts rows with a delay, so this project's own rows can be ahead of the organization total.
    const organizationRows = Math.max(syncedRowsProduct?.current_usage ?? 0, projectRows)
    return Object.fromEntries(
        Object.entries(billableRowsBySource).map(([sourceId, rows]) => [
            sourceId,
            organizationRows > 0 ? (amountUsd * rows) / organizationRows : 0,
        ])
    )
}

// Whole dollars with a "~", because cents would suggest more precision than an average-price split has.
export function formatEstimatedCostUsd(costUsd: number): string {
    if (costUsd <= 0) {
        return '$0'
    }
    if (costUsd < 1) {
        return '<$1'
    }
    return `~${humanFriendlyCurrency(Math.round(costUsd), 0)}`
}
