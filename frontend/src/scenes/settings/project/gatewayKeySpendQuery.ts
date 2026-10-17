import api from 'lib/api'

import { ProductKey } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'

export const GATEWAY_SPEND_WINDOW_DAYS = 30

export interface GatewayCredentialSpend {
    /** The $ai_credential the gateway stamped, or null for generations made before keys were attributed. */
    credential: string | null
    requests: number
    costUsd: number
}

// The events table is team-scoped, so the query needs no project filter.
export async function fetchGatewaySpendByCredential(): Promise<GatewayCredentialSpend[]> {
    const response = await api.queryHogQL(
        hogql`
            SELECT
                properties.$ai_credential AS credential,
                count() AS requests,
                round(sum(toFloat(properties.$ai_total_cost_usd)), 4) AS cost_usd
            FROM events
            WHERE event = '$ai_generation'
                AND properties.$ai_gateway = true
                AND timestamp >= now() - INTERVAL ${GATEWAY_SPEND_WINDOW_DAYS} DAY
            GROUP BY credential
            ORDER BY cost_usd DESC
            LIMIT 200
        `,
        { scene: 'Settings', productKey: ProductKey.AI_OBSERVABILITY, name: 'gateway_spend_by_key' }
    )
    return (response.results ?? []).map((row: unknown[]) => ({
        credential: row[0] ? String(row[0]) : null,
        requests: Number(row[1]) || 0,
        costUsd: Number(row[2]) || 0,
    }))
}
