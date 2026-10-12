import type { AuthService } from "@posthog/core/auth/auth";
import type { SavedInsight } from "@posthog/core/canvas/freeformSchemas";

// Thin authenticated helpers over the PostHog HTTP API, shared by the canvas
// services so the HogQL-query and current-user round-trips aren't duplicated.
// They take AuthService and use the ambient `fetch`; no caching here — callers
// cache as they see fit.

interface HogQLResponse {
  results?: unknown[];
  columns?: string[];
  error?: string | null;
  last_refresh?: string | null;
  hogql?: string | null;
}

export interface HogQLResult {
  columns: string[];
  /** Raw result rows from the query endpoint (each row is typically an array). */
  results: unknown[];
  /** ISO time the returned result was computed, when the endpoint reports it —
   * what callers judge cached-result freshness by. */
  lastRefresh: string | null;
  hogql?: string;
}

/**
 * Run a TYPED query node (`{ kind: "TrendsQuery" | "HogQLQuery" | … }`) against
 * the project's query endpoint and return its raw columns + rows. This is the
 * same endpoint + cache the insights/UI use, so a typed node returns the SAME
 * numbers the product shows. `refresh` selects the execution mode — pass
 * "blocking" for the cached avenue (serve a fresh cached result, else compute).
 * Throws on no selected project, an HTTP failure, or a query error; callers
 * map/shape the rows and decide how to treat an empty result.
 */
export async function runQuery(
  authService: AuthService,
  query: Record<string, unknown>,
  opts?: { refresh?: string },
): Promise<HogQLResult> {
  const body = await postQuery(authService, query, opts?.refresh);
  return {
    columns: Array.isArray(body.columns) ? body.columns.map(String) : [],
    results: Array.isArray(body.results) ? body.results : [],
    lastRefresh:
      typeof body.last_refresh === "string" ? body.last_refresh : null,
    ...(typeof body.hogql === "string" ? { hogql: body.hogql } : {}),
  };
}

/**
 * Read a query's CACHED result without ever computing (`refresh: "force_cache"`).
 * Returns null on a cache miss — the endpoint answers a miss with no `results`
 * key at all, which is distinct from a computed-but-empty `results: []`.
 */
export async function readCachedQuery(
  authService: AuthService,
  query: Record<string, unknown>,
): Promise<HogQLResult | null> {
  const body = await postQuery(authService, query, "force_cache");
  if (!Array.isArray(body.results)) return null;
  return {
    columns: Array.isArray(body.columns) ? body.columns.map(String) : [],
    results: body.results,
    lastRefresh:
      typeof body.last_refresh === "string" ? body.last_refresh : null,
  };
}

async function postQuery(
  authService: AuthService,
  query: Record<string, unknown>,
  refresh: string | undefined,
): Promise<HogQLResponse> {
  const { apiHost } = await authService.getValidAccessToken();
  const projectId = authService.getState().currentProjectId;
  if (projectId == null) {
    throw new Error("No PostHog project selected");
  }
  const response = await authService.authenticatedFetch(
    fetch,
    `${apiHost}/api/projects/${projectId}/query/`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, ...(refresh ? { refresh } : {}) }),
    },
  );
  if (!response.ok) {
    const detail = await response
      .json()
      .then((error: unknown) => {
        const errorDetail = (error as { detail?: unknown } | null)?.detail;
        return typeof errorDetail === "string" ? errorDetail : null;
      })
      .catch(() => null);
    throw new Error(detail ?? `Query failed (${response.status})`);
  }
  const body = (await response.json()) as HogQLResponse;
  if (body.error) throw new Error(body.error);
  return body;
}

/** A saved insight's stored result, fetched by short id. */
export interface InsightFetchResult {
  shortId: string;
  name: string | null;
  sourceKind: string | null;
  display: string | null;
  /** `insight.query.kind` — drives result-shape coercion (HogQLQuery → rows). */
  queryKind: string | null;
  columns: string[];
  /** The insight's precomputed `result` (series objects for trends, rows for SQL). */
  results: unknown[];
  /**
   * The SQL-variable values the server actually resolved this request with, keyed by
   * `code_name`. Read off the returned query (which the API rebuilds with the
   * overrides applied), so it reflects what the numbers were computed from — not
   * what we asked for. Empty for an insight with no variables.
   */
  resolvedVariables: Record<string, unknown>;
}

/** A query node as far as this module cares: a kind, maybe a wrapped source, maybe variables. */
interface InsightQueryNode {
  kind?: string;
  source?: InsightQueryNode | null;
  variables?: Record<string, { code_name?: string; value?: unknown }> | null;
}

// SQL variables live on the HogQLQuery node, which sits under one or more wrapper
// nodes (DataVisualizationNode, InsightVizNode) — the same `source` chain the API
// walks when it applies the overrides. Bounded rather than blindly recursive: a
// malformed/cyclic node from the wire shouldn't spin here.
const MAX_QUERY_NODE_DEPTH = 5;

function readResolvedVariables(
  query: InsightQueryNode | null | undefined,
): Record<string, unknown> {
  let node = query;
  for (let depth = 0; node && depth < MAX_QUERY_NODE_DEPTH; depth++) {
    if (node.variables) {
      // Re-key by code_name: the API keys these by variable uuid, but code_name is
      // what the insight's SQL references and what callers pass.
      return Object.fromEntries(
        Object.values(node.variables)
          .filter((variable) => typeof variable?.code_name === "string")
          .map((variable) => [variable.code_name as string, variable.value]),
      );
    }
    node = node.source;
  }
  return {};
}

// `variables_override` wants full HogQLVariable-shaped entries. The server re-keys
// them by matching `code_name` against the project's variables and fills in the real
// uuid, so a code_name-keyed map is enough — no uuid lookup round-trip needed here.
// An entry WITHOUT `code_name` is dropped server-side without comment, hence the
// explicit field rather than relying on the map key.
function buildVariablesOverride(
  variables: Record<string, unknown>,
): Record<string, { code_name: string; value: unknown }> {
  return Object.fromEntries(
    Object.entries(variables).map(([codeName, value]) => [
      codeName,
      { code_name: codeName, value },
    ]),
  );
}

interface InsightRow {
  short_id?: string;
  name?: string | null;
  derived_name?: string | null;
  query?: InsightQueryNode | null;
  columns?: string[] | null;
  result?: unknown;
}

async function fetchInsights(
  authService: AuthService,
  params: URLSearchParams,
  action: string,
): Promise<InsightRow[]> {
  const { apiHost } = await authService.getValidAccessToken();
  const projectId = authService.getState().currentProjectId;
  if (projectId == null) {
    throw new Error("No PostHog project selected");
  }
  const response = await authService.authenticatedFetch(
    fetch,
    `${apiHost}/api/projects/${projectId}/insights/?${params.toString()}`,
  );
  if (!response.ok) {
    throw new Error(`${action} failed (${response.status})`);
  }
  const body = (await response.json()) as { results?: InsightRow[] };
  return body.results ?? [];
}

/**
 * Fetch a SAVED insight by `short_id` and return its STORED result straight from
 * the insights endpoint (`/insights/?short_id=…&refresh=blocking`) — the same
 * cache the PostHog UI reads, so the numbers match the insight as shown there.
 * This is how a canvas loads a proven, saved insight instead of re-running a raw
 * query against `/query/`.
 *
 * `dateRange` re-scopes the insight for this request only via `filters_override`
 * (the product's per-request override) — NOT the flat `date_from`/`date_to` query
 * params, which are LIST filters that would exclude the insight from the result
 * set. `short_id` still matches the insight regardless, so the lookup is robust;
 * if the saved insight's window can't be overridden (e.g. a raw-SQL insight) it
 * simply returns its saved window. Throws on no selected project, an HTTP
 * failure, or an unknown short id.
 *
 * `variables` overrides the insight's HogQL variables for this request via
 * `variables_override` — keyed by `code_name`, values applied to both the returned
 * query and the result it's computed from. The values the server actually landed on
 * come back as `resolvedVariables`; callers must compare, because the API drops
 * unmatched entries silently (see CanvasDataService.loadInsight).
 */
export async function fetchInsightByShortId(
  authService: AuthService,
  shortId: string,
  opts?: {
    dateRange?: { date_from?: string | null; date_to?: string | null };
    variables?: Record<string, unknown>;
  },
): Promise<InsightFetchResult> {
  const params = new URLSearchParams({
    short_id: shortId,
    refresh: "blocking",
  });
  if (opts?.dateRange) {
    params.set("filters_override", JSON.stringify(opts.dateRange));
  }
  if (opts?.variables && Object.keys(opts.variables).length > 0) {
    params.set(
      "variables_override",
      JSON.stringify(buildVariablesOverride(opts.variables)),
    );
  }

  const [insight] = await fetchInsights(authService, params, "Insight load");
  if (!insight) {
    throw new Error(`Insight "${shortId}" not found`);
  }

  const source = (insight.query as { source?: Record<string, unknown> } | null)
    ?.source;
  const trendsFilter = source?.trendsFilter as { display?: string } | undefined;
  return {
    shortId,
    name: insight.name || insight.derived_name || null,
    sourceKind:
      (typeof source?.kind === "string" ? source.kind : null) ??
      insight.query?.kind ??
      null,
    display: trendsFilter?.display ?? null,
    queryKind: insight.query?.kind ?? null,
    columns: Array.isArray(insight.columns) ? insight.columns.map(String) : [],
    results: Array.isArray(insight.result) ? insight.result : [],
    resolvedVariables: readResolvedVariables(insight.query),
  };
}

export interface CurrentUser {
  /** The user's PostHog distinct_id (event attribution). */
  distinctId?: string;
  /** Display label: full name, else email. */
  label?: string;
}

/**
 * Fetch the signed-in user from /api/users/@me/. Returns null on failure (never
 * throws) so callers can degrade gracefully. No caching — callers cache.
 */
export async function fetchCurrentUser(
  authService: AuthService,
): Promise<CurrentUser | null> {
  try {
    const { apiHost } = await authService.getValidAccessToken();
    const res = await authService.authenticatedFetch(
      fetch,
      `${apiHost}/api/users/@me/`,
    );
    if (!res.ok) return null;
    const data = (await res.json()) as {
      first_name?: string | null;
      last_name?: string | null;
      email?: string | null;
      distinct_id?: string | null;
    };
    const name = [data.first_name, data.last_name]
      .filter(Boolean)
      .join(" ")
      .trim();
    return {
      distinctId: data.distinct_id ?? undefined,
      label: name || data.email || undefined,
    };
  } catch {
    return null;
  }
}

export async function listSavedInsights(
  authService: AuthService,
  search = "",
): Promise<SavedInsight[]> {
  const params = new URLSearchParams({
    saved: "true",
    basic: "true",
    limit: "200",
    order: "-last_modified_at",
  });
  if (search.trim()) params.set("search", search.trim());
  const insights = await fetchInsights(authService, params, "Insight list");
  return insights.flatMap((insight) =>
    insight.short_id
      ? [
          {
            shortId: insight.short_id,
            name:
              insight.name?.trim() ||
              insight.derived_name?.trim() ||
              "Untitled insight",
          },
        ]
      : [],
  );
}
