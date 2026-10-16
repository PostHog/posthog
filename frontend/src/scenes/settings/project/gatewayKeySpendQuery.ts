import { performQuery } from '~/queries/query'
import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { hogql, setLatestVersionsOnQuery } from '~/queries/utils'

export const GATEWAY_SPEND_WINDOW_DAYS = 30

export interface GatewayCredentialSpend {
    /** The $ai_credential the gateway stamped, or null for generations made before keys were attributed. */
    credential: string | null
    requests: number
    costUsd: number
}

// The events table is team-scoped, so the query needs no project filter.
// The query scans every generation in the window, which can outrun a sync request on a large
// project, so it runs async and polls.
export async function fetchGatewaySpendByCredential(): Promise<GatewayCredentialSpend[]> {
    const query: HogQLQuery = setLatestVersionsOnQuery({
        kind: NodeKind.HogQLQuery,
        query: hogql`
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
        tags: { scene: 'Settings', productKey: 'ai_gateway', name: 'gateway_spend_by_key' },
    })
    const response = await performQuery(query, undefined, 'async')
    return (response.results ?? []).map((row: unknown[]) => ({
        credential: row[0] ? String(row[0]) : null,
        requests: Number(row[1]) || 0,
        costUsd: Number(row[2]) || 0,
    }))
}
