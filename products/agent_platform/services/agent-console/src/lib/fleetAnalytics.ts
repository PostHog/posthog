/**
 * Fleet analytics — rolls up the agents' `$ai_*` AI-observability events (the
 * runner captures them into this team's own project) into a cross-agent
 * dashboard. Read-only HogQL via `runHogql`; everything is scoped to
 * `$ai_origin = 'agent_platform_runner'` so a team's *other* LLM usage (their
 * own posthog-ai apps) never bleeds into the agent view.
 *
 * One round-trip per panel, fired in parallel. All best-effort: a failed query
 * yields an empty panel rather than a broken page.
 */

import { listAgents, runHogql } from './apiClient'

/** Only the agents' own traffic — not the team's other LLM events. */
const AGENT_ORIGIN = "properties.$ai_origin = 'agent_platform_runner'"

/**
 * Shared WHERE scope. `applicationId` (a trusted UUID from the agent record)
 * narrows the board to a single agent for the per-agent Observability tab.
 */
function scope(applicationId?: string): string {
    const agent = applicationId ? ` AND properties.$agent_application_id = '${applicationId}'` : ''
    return `${AGENT_ORIGIN}${agent}`
}

const kpiQuery = (id?: string): string => `
SELECT
  coalesce(sum(toFloat(properties.$ai_total_cost_usd)), 0) AS cost,
  uniq(properties.$ai_trace_id) AS sessions,
  countIf(toString(properties.$ai_is_error) = 'true') AS errors,
  count() AS generations,
  coalesce(quantile(0.95)(toFloat(properties.$ai_latency)), 0) AS p95
FROM events
WHERE event = '$ai_generation' AND ${scope(id)}
  AND timestamp > now() - INTERVAL 7 DAY
`

const dailyQuery = (id?: string): string => `
SELECT
  toStartOfDay(timestamp) AS day,
  coalesce(sum(toFloat(properties.$ai_total_cost_usd)), 0) AS cost,
  uniq(properties.$ai_trace_id) AS sessions,
  countIf(toString(properties.$ai_is_error) = 'true') AS errors,
  count() AS generations
FROM events
WHERE event = '$ai_generation' AND ${scope(id)}
  AND timestamp > now() - INTERVAL 14 DAY
GROUP BY day ORDER BY day
`

const perAgentQuery = (id?: string): string => `
SELECT
  properties.$agent_application_id AS agent_id,
  uniq(properties.$ai_trace_id) AS sessions,
  count() AS generations,
  coalesce(sum(toFloat(properties.$ai_total_cost_usd)), 0) AS cost,
  coalesce(sum(toInt(properties.$ai_input_tokens)), 0)
    + coalesce(sum(toInt(properties.$ai_output_tokens)), 0) AS tokens,
  countIf(toString(properties.$ai_is_error) = 'true') AS errors,
  coalesce(quantile(0.95)(toFloat(properties.$ai_latency)), 0) AS p95
FROM events
WHERE event = '$ai_generation' AND ${scope(id)}
  AND timestamp > now() - INTERVAL 7 DAY AND notEmpty(properties.$agent_application_id)
GROUP BY agent_id ORDER BY cost DESC LIMIT 50
`

const byModelQuery = (id?: string): string => `
SELECT
  properties.$ai_model AS model,
  coalesce(sum(toFloat(properties.$ai_total_cost_usd)), 0) AS cost,
  count() AS calls
FROM events
WHERE event = '$ai_generation' AND ${scope(id)}
  AND timestamp > now() - INTERVAL 7 DAY AND notEmpty(properties.$ai_model)
GROUP BY model ORDER BY cost DESC LIMIT 8
`

const toolErrorsQuery = (id?: string): string => `
SELECT
  properties.$ai_span_name AS tool,
  count() AS calls,
  countIf(toString(properties.$ai_is_error) = 'true') AS errors
FROM events
WHERE event = '$ai_span' AND ${scope(id)}
  AND timestamp > now() - INTERVAL 7 DAY AND notEmpty(properties.$ai_span_name)
GROUP BY tool ORDER BY errors DESC, calls DESC LIMIT 8
`

export interface FleetKpis {
    spendUsd: number
    sessions: number
    /** 0..1 — share of generations that errored. */
    failureRate: number
    /** p95 model latency, seconds. */
    p95LatencyS: number
}

export interface FleetDaily {
    /** Short date labels, oldest → newest (14 days). */
    labels: string[]
    spend: number[]
    sessions: number[]
    /** 0..1 per day. */
    failureRate: number[]
}

export interface FleetDeltas {
    /** Percent change vs the prior 7 days (e.g. 12 = +12%). `null` when undefined. */
    spend: number | null
    sessions: number | null
    failureRatePoints: number | null
}

export interface AgentRow {
    id: string
    name: string
    sessions: number
    spendUsd: number
    failureRate: number
    p95LatencyS: number
    tokens: number
}

export interface ModelRow {
    model: string
    spendUsd: number
    calls: number
}

export interface ToolRow {
    tool: string
    calls: number
    errors: number
    errorRate: number
}

export interface FleetAnalyticsData {
    kpis: FleetKpis
    daily: FleetDaily
    deltas: FleetDeltas
    byAgent: AgentRow[]
    byModel: ModelRow[]
    toolErrors: ToolRow[]
    /** True when there is no agent AI activity in the window — drives the empty state. */
    empty: boolean
}

/** Zeroed placeholder rendered while the first load is in flight. */
export const EMPTY_ANALYTICS: FleetAnalyticsData = {
    kpis: { spendUsd: 0, sessions: 0, failureRate: 0, p95LatencyS: 0 },
    daily: { labels: [], spend: [], sessions: [], failureRate: [] },
    deltas: { spend: null, sessions: null, failureRatePoints: null },
    byAgent: [],
    byModel: [],
    toolErrors: [],
    empty: true,
}

function num(v: unknown): number {
    const n = typeof v === 'number' ? v : Number(v)
    return Number.isFinite(n) ? n : 0
}

function pctChange(recent: number, prior: number): number | null {
    if (prior <= 0) {
        return null
    }
    return ((recent - prior) / prior) * 100
}

function shortId(id: string): string {
    return id.split('-').at(-1)?.slice(0, 8) ?? id.slice(0, 8)
}

/** `applicationId` scopes the board to a single agent (the per-agent Observability tab). */
export async function loadFleetAnalytics(teamId: number, applicationId?: string): Promise<FleetAnalyticsData> {
    const empty = { results: [] as unknown[][], columns: [] as string[] }
    const [agents, kpiRes, dailyRes, perAgentRes, byModelRes, toolErrRes] = await Promise.all([
        listAgents(teamId).catch(() => []),
        // KPI is the gate — let it throw so a systemic failure (auth, bad query)
        // surfaces as an error state rather than a silent empty board. The
        // secondary panels degrade individually.
        runHogql(teamId, kpiQuery(applicationId)),
        runHogql(teamId, dailyQuery(applicationId)).catch(() => empty),
        runHogql(teamId, perAgentQuery(applicationId)).catch(() => empty),
        runHogql(teamId, byModelQuery(applicationId)).catch(() => empty),
        runHogql(teamId, toolErrorsQuery(applicationId)).catch(() => empty),
    ])

    const nameById = new Map(agents.map((a) => [a.id, a.name]))

    // KPIs (single row): cost, sessions, errors, generations, p95
    const k = kpiRes.results[0] ?? [0, 0, 0, 0, 0]
    const generations = num(k[3])
    const kpis: FleetKpis = {
        spendUsd: num(k[0]),
        sessions: num(k[1]),
        failureRate: generations > 0 ? num(k[2]) / generations : 0,
        p95LatencyS: num(k[4]),
    }

    // Daily 14-day series → sparklines + prior-vs-recent deltas.
    const dayRows = dailyRes.results
    const labels = dayRows.map((r) => formatDay(String(r[0])))
    const spend = dayRows.map((r) => num(r[1]))
    const sessionsByDay = dayRows.map((r) => num(r[2]))
    const errorsByDay = dayRows.map((r) => num(r[3]))
    const genByDay = dayRows.map((r) => num(r[4]))
    const failureRate = dayRows.map((_, i) => (genByDay[i] > 0 ? errorsByDay[i] / genByDay[i] : 0))

    const recent = (arr: number[]): number => arr.slice(-7).reduce((s, v) => s + v, 0)
    const prior = (arr: number[]): number => arr.slice(0, Math.max(0, arr.length - 7)).reduce((s, v) => s + v, 0)
    const recentGen = recent(genByDay)
    const priorGen = prior(genByDay)
    const recentRate = recentGen > 0 ? recent(errorsByDay) / recentGen : 0
    const priorRate = priorGen > 0 ? prior(errorsByDay) / priorGen : 0
    const deltas: FleetDeltas = {
        spend: pctChange(recent(spend), prior(spend)),
        sessions: pctChange(recent(sessionsByDay), prior(sessionsByDay)),
        failureRatePoints: priorGen > 0 ? (recentRate - priorRate) * 100 : null,
    }

    const byAgent: AgentRow[] = perAgentRes.results.map((r) => {
        const id = String(r[0])
        const gens = num(r[2])
        return {
            id,
            name: nameById.get(id) ?? shortId(id),
            sessions: num(r[1]),
            spendUsd: num(r[3]),
            tokens: num(r[4]),
            failureRate: gens > 0 ? num(r[5]) / gens : 0,
            p95LatencyS: num(r[6]),
        }
    })

    const byModel: ModelRow[] = byModelRes.results.map((r) => ({
        model: String(r[0]),
        spendUsd: num(r[1]),
        calls: num(r[2]),
    }))

    const toolErrors: ToolRow[] = toolErrRes.results.map((r) => {
        const calls = num(r[1])
        const errors = num(r[2])
        return { tool: String(r[0]), calls, errors, errorRate: calls > 0 ? errors / calls : 0 }
    })

    return {
        kpis,
        daily: { labels, spend, sessions: sessionsByDay, failureRate },
        deltas,
        byAgent,
        byModel,
        toolErrors,
        empty: kpis.sessions === 0 && byAgent.length === 0 && generations === 0,
    }
}

function formatDay(iso: string): string {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) {
        return iso.slice(5, 10)
    }
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}
