import { LemonSkeleton, LemonTable } from '@posthog/lemon-ui'

import api from 'lib/api'
import { Sparkline } from 'lib/components/Sparkline'
import { dayjs, dayjsNowInTimezone } from 'lib/dayjs'
import { humanFriendlyCurrency, humanFriendlyNumber } from 'lib/utils/numbers'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

const USAGE_WINDOW_DAYS = 30

// Gateway usage is read from $ai_generation events the gateway stamps with $ai_gateway = true,
// which separates them from SDK-emitted LLM events that share the $ai_generation event name.
// The events table is team-scoped and api.query resolves the team from the request context.
const GATEWAY_EVENTS_WHERE = `event = '$ai_generation' AND properties.$ai_gateway = true AND timestamp >= now() - INTERVAL ${USAGE_WINDOW_DAYS} DAY`

export interface GatewayUsage {
    requests: number
    inputTokens: number
    outputTokens: number
    costUsd: number
}

export interface GatewaySpendPoint {
    day: string
    costUsd: number
}

export interface GatewayModelUsage {
    model: string
    requests: number
    inputTokens: number
    outputTokens: number
    costUsd: number
}

export async function fetchGatewaySpendByDay(): Promise<GatewaySpendPoint[]> {
    const query: HogQLQuery = {
        kind: NodeKind.HogQLQuery,
        query: `
            SELECT
                toStartOfDay(timestamp) AS day,
                round(sum(toFloat(properties.$ai_total_cost_usd)), 4) AS cost_usd
            FROM events
            WHERE ${GATEWAY_EVENTS_WHERE}
            GROUP BY day
            ORDER BY day
        `,
    }
    const response = await api.query(query)
    return (response.results ?? []).map((row: unknown[]) => ({
        day: String(row[0]),
        costUsd: Number(row[1]) || 0,
    }))
}

export async function fetchGatewayUsageByModel(): Promise<GatewayModelUsage[]> {
    const query: HogQLQuery = {
        kind: NodeKind.HogQLQuery,
        query: `
            SELECT
                properties.$ai_model AS model,
                count() AS requests,
                sum(toFloat(properties.$ai_input_tokens)) AS input_tokens,
                sum(toFloat(properties.$ai_output_tokens)) AS output_tokens,
                round(sum(toFloat(properties.$ai_total_cost_usd)), 4) AS cost_usd
            FROM events
            WHERE ${GATEWAY_EVENTS_WHERE}
            GROUP BY model
            ORDER BY cost_usd DESC
            LIMIT 100
        `,
    }
    const response = await api.query(query)
    return (response.results ?? []).map((row: unknown[]) => ({
        model: row[0] ? String(row[0]) : 'unknown',
        requests: Number(row[1]) || 0,
        inputTokens: Number(row[2]) || 0,
        outputTokens: Number(row[3]) || 0,
        costUsd: Number(row[4]) || 0,
    }))
}

// Pad the raw per-day spend into a contiguous 30-day series so the chart has no gaps for idle days.
export function buildSpendChartData(
    points: GatewaySpendPoint[],
    timezone: string
): { data: number[]; labels: string[] } {
    const byDay = new Map(points.map((point) => [dayjs(point.day).format('YYYY-MM-DD'), point.costUsd]))
    const start = dayjsNowInTimezone(timezone)
        .startOf('day')
        .subtract(USAGE_WINDOW_DAYS - 1, 'day')
    const data: number[] = []
    const labels: string[] = []
    for (let i = 0; i < USAGE_WINDOW_DAYS; i++) {
        const day = start.add(i, 'day')
        data.push(byDay.get(day.format('YYYY-MM-DD')) ?? 0)
        labels.push(day.format('MMM D'))
    }
    return { data, labels }
}

function MetricTile({ label, value, loading }: { label: string; value: string | null; loading: boolean }): JSX.Element {
    return (
        <div className="border rounded p-4 min-w-32 flex-1">
            <div className="text-secondary text-xs uppercase">{label}</div>
            {loading || value === null ? (
                <LemonSkeleton className="h-7 w-16 mt-1" />
            ) : (
                <div className="text-2xl font-semibold">{value}</div>
            )}
        </div>
    )
}

export function UsageMetrics({ usage, loading }: { usage: GatewayUsage | null; loading: boolean }): JSX.Element {
    return (
        <>
            <MetricTile label="Spend" value={usage ? humanFriendlyCurrency(usage.costUsd) : null} loading={loading} />
            <MetricTile label="Requests" value={usage ? humanFriendlyNumber(usage.requests) : null} loading={loading} />
            <MetricTile
                label="Input tokens"
                value={usage ? humanFriendlyNumber(usage.inputTokens) : null}
                loading={loading}
            />
            <MetricTile
                label="Output tokens"
                value={usage ? humanFriendlyNumber(usage.outputTokens) : null}
                loading={loading}
            />
        </>
    )
}

export function SpendChart({
    data,
    labels,
    loading,
}: {
    data: number[]
    labels: string[]
    loading: boolean
}): JSX.Element {
    const hasSpend = data.some((value) => value > 0)
    return (
        <div className="flex flex-col gap-1">
            <span className="text-secondary text-xs uppercase">Spend per day</span>
            {!loading && !hasSpend ? (
                <div className="h-16 flex items-center text-secondary text-sm">No spend in the last 30 days yet</div>
            ) : (
                <Sparkline
                    className="h-16"
                    type="bar"
                    data={data}
                    labels={labels}
                    color="success"
                    loading={loading}
                    renderTooltipValue={(value) => humanFriendlyCurrency(value, 4)}
                />
            )}
        </div>
    )
}

export function ModelBreakdownTable({ rows, loading }: { rows: GatewayModelUsage[]; loading: boolean }): JSX.Element {
    return (
        <LemonTable
            dataSource={rows}
            loading={loading}
            rowKey="model"
            size="small"
            columns={[
                { title: 'Model', dataIndex: 'model' },
                {
                    title: 'Requests',
                    dataIndex: 'requests',
                    render: (_, row) => humanFriendlyNumber(row.requests),
                    sorter: (a, b) => a.requests - b.requests,
                },
                {
                    title: 'Tokens',
                    key: 'tokens',
                    render: (_, row) => humanFriendlyNumber(row.inputTokens + row.outputTokens),
                    sorter: (a, b) => a.inputTokens + a.outputTokens - (b.inputTokens + b.outputTokens),
                },
                {
                    title: 'Spend',
                    dataIndex: 'costUsd',
                    render: (_, row) => humanFriendlyCurrency(row.costUsd, 4),
                    sorter: (a, b) => a.costUsd - b.costUsd,
                },
            ]}
            emptyState="No gateway usage in the last 30 days yet"
        />
    )
}
