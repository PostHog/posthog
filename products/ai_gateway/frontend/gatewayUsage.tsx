import { LemonSkeleton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { humanFriendlyNumber } from 'lib/utils'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

// Window for the usage panels. $ai_gateway_slug lands on $ai_generation events
// from the gateway (ai-gateway #80), so these read empty until that ships.
const USAGE_WINDOW_DAYS = 30

export interface GatewayUsage {
    requests: number
    inputTokens: number
    outputTokens: number
    costUsd: number
}

// Summary usage from $ai_generation events. With a slug, scopes to that gateway;
// without one, sums across every gateway-attributed event for the project.
// api.query resolves the team from the request context, so no project id is needed.
export async function fetchGatewayUsage(slug?: string): Promise<GatewayUsage> {
    const slugFilter = slug ? 'properties.$ai_gateway_slug = {slug}' : 'properties.$ai_gateway_slug IS NOT NULL'
    const query: HogQLQuery = {
        kind: NodeKind.HogQLQuery,
        query: `
            SELECT
                count() AS requests,
                sum(toFloat(properties.$ai_input_tokens)) AS input_tokens,
                sum(toFloat(properties.$ai_output_tokens)) AS output_tokens,
                round(sum(toFloat(properties.$ai_total_cost_usd)), 4) AS cost_usd
            FROM events
            WHERE event = '$ai_generation'
                AND ${slugFilter}
                AND timestamp >= now() - INTERVAL ${USAGE_WINDOW_DAYS} DAY
        `,
        values: slug ? { slug } : {},
    }
    const response = await api.query(query)
    const row = response.results?.[0] ?? []
    return {
        requests: Number(row[0]) || 0,
        inputTokens: Number(row[1]) || 0,
        outputTokens: Number(row[2]) || 0,
        costUsd: Number(row[3]) || 0,
    }
}

export function UsageTiles({ usage, loading }: { usage: GatewayUsage | null; loading: boolean }): JSX.Element {
    return (
        <div className="flex gap-2 flex-wrap">
            <UsageTile label="Requests" value={usage ? humanFriendlyNumber(usage.requests) : null} loading={loading} />
            <UsageTile
                label="Tokens"
                value={usage ? humanFriendlyNumber(usage.inputTokens + usage.outputTokens) : null}
                loading={loading}
            />
            <UsageTile label="Cost" value={usage ? `$${usage.costUsd.toFixed(2)}` : null} loading={loading} />
        </div>
    )
}

function UsageTile({ label, value, loading }: { label: string; value: string | null; loading: boolean }): JSX.Element {
    return (
        <div className="border rounded p-4 min-w-32">
            <div className="text-secondary text-xs uppercase">{label}</div>
            {loading || value === null ? (
                <LemonSkeleton className="h-7 w-16 mt-1" />
            ) : (
                <div className="text-2xl font-semibold">{value}</div>
            )}
        </div>
    )
}
