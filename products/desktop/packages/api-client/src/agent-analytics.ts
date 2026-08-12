// Agent observability analytics — rolls up the agents' `$ai_*` events into a
// cross-agent / per-agent dashboard. Read-only HogQL via the `/query/` endpoint.
//
// Scoped on `$agent_application_id` (the per-agent attribution key), NOT
// `$ai_origin`: on the ai-gateway path the cost-bearing `$ai_generation` is
// emitted by the gateway, which carries `$agent_application_id` (forwarded by
// the runner via X-PostHog-Properties) but not `$ai_origin`. The attribution
// key is present on generations (gateway or direct), tool spans, and traces, so
// it unifies both paths and keeps a team's other LLM usage out of the view.
//
// The query builders + shaping are kept here (pure, unit-tested) so the client
// method stays a thin "fire queries, shape result" passthrough.

import type {
  AgentAnalyticsData,
  AgentAnalyticsModelRow,
  AgentAnalyticsToolRow,
} from "@posthog/shared/agent-platform-types";

/** A raw HogQL `/query/` result grid: rows of cells plus column names. */
export interface HogQLGrid {
  results: unknown[][];
  columns: string[];
}

/** The five panels' raw grids, keyed by panel. */
export interface AgentAnalyticsRaw {
  kpi: HogQLGrid;
  daily: HogQLGrid;
  perAgent: HogQLGrid;
  byModel: HogQLGrid;
  toolErrors: HogQLGrid;
}

/** Any agent-platform traffic — a team's other LLM usage has no agent id. */
const AGENT_SCOPE = "notEmpty(properties.$agent_application_id)";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Shared WHERE scope. With an `applicationId` (per-agent tab) it narrows to that
 * agent; without one (fleet board) it matches any agent traffic via the
 * attribution key. `applicationId` is a trusted server UUID, but reject
 * non-UUIDs before interpolating into HogQL rather than rely on that.
 */
function scope(applicationId?: string): string {
  if (applicationId && !UUID_RE.test(applicationId)) {
    throw new Error("agent analytics: applicationId must be a UUID");
  }
  return applicationId
    ? `properties.$agent_application_id = '${applicationId}'`
    : AGENT_SCOPE;
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
`;

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
`;

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
  AND timestamp > now() - INTERVAL 7 DAY
GROUP BY agent_id ORDER BY cost DESC LIMIT 50
`;

const byModelQuery = (id?: string): string => `
SELECT
  properties.$ai_model AS model,
  coalesce(sum(toFloat(properties.$ai_total_cost_usd)), 0) AS cost,
  count() AS calls
FROM events
WHERE event = '$ai_generation' AND ${scope(id)}
  AND timestamp > now() - INTERVAL 7 DAY AND notEmpty(properties.$ai_model)
GROUP BY model ORDER BY cost DESC LIMIT 8
`;

const toolErrorsQuery = (id?: string): string => `
SELECT
  properties.$ai_span_name AS tool,
  count() AS calls,
  countIf(toString(properties.$ai_is_error) = 'true') AS errors
FROM events
WHERE event = '$ai_span' AND ${scope(id)}
  AND timestamp > now() - INTERVAL 7 DAY AND notEmpty(properties.$ai_span_name)
GROUP BY tool ORDER BY errors DESC, calls DESC LIMIT 8
`;

/**
 * Build the five panel queries. `applicationId` scopes them to a single agent
 * (the per-agent Observability tab); omit it for the fleet-wide board.
 */
export function buildAgentAnalyticsQueries(applicationId?: string): {
  kpi: string;
  daily: string;
  perAgent: string;
  byModel: string;
  toolErrors: string;
} {
  return {
    kpi: kpiQuery(applicationId),
    daily: dailyQuery(applicationId),
    perAgent: perAgentQuery(applicationId),
    byModel: byModelQuery(applicationId),
    toolErrors: toolErrorsQuery(applicationId),
  };
}

const EMPTY_GRID: HogQLGrid = { results: [], columns: [] };

/** Zeroed placeholder rendered while the first load is in flight. */
export const EMPTY_AGENT_ANALYTICS: AgentAnalyticsData = {
  kpis: { spendUsd: 0, sessions: 0, failureRate: 0, p95LatencyS: 0 },
  daily: { labels: [], spend: [], sessions: [], failureRate: [] },
  deltas: { spend: null, sessions: null, failureRatePoints: null },
  byAgent: [],
  byModel: [],
  toolErrors: [],
  empty: true,
};

function num(v: unknown): number {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : 0;
}

function pctChange(recent: number, prior: number): number | null {
  if (prior <= 0) {
    return null;
  }
  return ((recent - prior) / prior) * 100;
}

function shortId(id: string): string {
  return id.split("-").at(-1)?.slice(0, 8) ?? id.slice(0, 8);
}

function formatDay(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return iso.slice(5, 10);
  }
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** Coerce a raw HogQL grid into rows of cells, dropping non-array rows. */
function rows(grid: HogQLGrid | undefined): unknown[][] {
  return (grid?.results ?? []).filter((r): r is unknown[] => Array.isArray(r));
}

/**
 * Fold the five raw HogQL grids into the analytics dashboard shape. Pure: the
 * caller fires the queries (and resolves `nameById` from the agent list).
 */
export function shapeAgentAnalytics(
  raw: Partial<AgentAnalyticsRaw>,
  nameById: Map<string, string> = new Map(),
): AgentAnalyticsData {
  // KPIs (single row): cost, sessions, errors, generations, p95
  const k = rows(raw.kpi)[0] ?? [0, 0, 0, 0, 0];
  const generations = num(k[3]);
  const kpis = {
    spendUsd: num(k[0]),
    sessions: num(k[1]),
    failureRate: generations > 0 ? num(k[2]) / generations : 0,
    p95LatencyS: num(k[4]),
  };

  // Daily 14-day series → sparklines + prior-vs-recent deltas.
  const dayRows = rows(raw.daily);
  const labels = dayRows.map((r) => formatDay(String(r[0])));
  const spend = dayRows.map((r) => num(r[1]));
  const sessionsByDay = dayRows.map((r) => num(r[2]));
  const errorsByDay = dayRows.map((r) => num(r[3]));
  const genByDay = dayRows.map((r) => num(r[4]));
  const failureRate = dayRows.map((_, i) =>
    genByDay[i] > 0 ? errorsByDay[i] / genByDay[i] : 0,
  );

  const recent = (arr: number[]): number =>
    arr.slice(-7).reduce((s, v) => s + v, 0);
  const prior = (arr: number[]): number =>
    arr.slice(0, Math.max(0, arr.length - 7)).reduce((s, v) => s + v, 0);
  const recentGen = recent(genByDay);
  const priorGen = prior(genByDay);
  const recentRate = recentGen > 0 ? recent(errorsByDay) / recentGen : 0;
  const priorRate = priorGen > 0 ? prior(errorsByDay) / priorGen : 0;
  const deltas = {
    spend: pctChange(recent(spend), prior(spend)),
    sessions: pctChange(recent(sessionsByDay), prior(sessionsByDay)),
    failureRatePoints: priorGen > 0 ? (recentRate - priorRate) * 100 : null,
  };

  const byAgent = rows(raw.perAgent).map((r) => {
    const id = String(r[0]);
    const gens = num(r[2]);
    return {
      id,
      name: nameById.get(id) ?? shortId(id),
      sessions: num(r[1]),
      spendUsd: num(r[3]),
      tokens: num(r[4]),
      failureRate: gens > 0 ? num(r[5]) / gens : 0,
      p95LatencyS: num(r[6]),
    };
  });

  const byModel: AgentAnalyticsModelRow[] = rows(raw.byModel).map((r) => ({
    model: String(r[0]),
    spendUsd: num(r[1]),
    calls: num(r[2]),
  }));

  const toolErrors: AgentAnalyticsToolRow[] = rows(raw.toolErrors).map((r) => {
    const calls = num(r[1]);
    const errors = num(r[2]);
    return {
      tool: String(r[0]),
      calls,
      errors,
      errorRate: calls > 0 ? errors / calls : 0,
    };
  });

  return {
    kpis,
    daily: { labels, spend, sessions: sessionsByDay, failureRate },
    deltas,
    byAgent,
    byModel,
    toolErrors,
    empty: kpis.sessions === 0 && byAgent.length === 0 && generations === 0,
  };
}

export { EMPTY_GRID };
