import type { AuthService } from "@posthog/core/auth/auth";

// Thin authenticated helpers over the PostHog HTTP API, shared by the canvas
// services so the HogQL-query and current-user round-trips aren't duplicated.
// They take AuthService and use the ambient `fetch`; no caching here — callers
// cache as they see fit.

interface HogQLResponse {
  results?: unknown[];
  columns?: string[];
  error?: string | null;
}

export interface HogQLResult {
  columns: string[];
  /** Raw result rows from the query endpoint (each row is typically an array). */
  results: unknown[];
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
      body: JSON.stringify({
        query,
        ...(opts?.refresh ? { refresh: opts.refresh } : {}),
      }),
    },
  );

  if (!response.ok) {
    throw new Error(`Query failed (${response.status})`);
  }
  const body = (await response.json()) as HogQLResponse;
  if (body.error) throw new Error(body.error);

  return {
    columns: Array.isArray(body.columns) ? body.columns.map(String) : [],
    results: Array.isArray(body.results) ? body.results : [],
  };
}

/**
 * Run an inline HogQL string. A thin wrapper over {@link runQuery} that boxes the
 * SQL into a HogQLQuery node — the escape hatch for shapes a typed node can't
 * express. Prefer a typed node (TrendsQuery/etc.) for standard metrics.
 */
export async function runHogQLQuery(
  authService: AuthService,
  hogql: string,
  opts?: { refresh?: string },
): Promise<HogQLResult> {
  // `tags.productKey` attributes the query to a product so PostHog's
  // query-tagging guard is satisfied (it hard-fails untagged ClickHouse queries
  // in local dev). The desktop canvas/dashboard surfaces are the "max" product.
  return runQuery(
    authService,
    { kind: "HogQLQuery", query: hogql, tags: { productKey: "max" } },
    opts,
  );
}

/** A saved insight's stored result, fetched by short id. */
export interface InsightFetchResult {
  shortId: string;
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
  const { apiHost } = await authService.getValidAccessToken();
  const projectId = authService.getState().currentProjectId;
  if (projectId == null) {
    throw new Error("No PostHog project selected");
  }

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

  const response = await authService.authenticatedFetch(
    fetch,
    `${apiHost}/api/projects/${projectId}/insights/?${params.toString()}`,
  );
  if (!response.ok) {
    throw new Error(`Insight load failed (${response.status})`);
  }

  const body = (await response.json()) as {
    results?: Array<{
      short_id?: string;
      query?: InsightQueryNode | null;
      columns?: string[] | null;
      result?: unknown;
    }>;
  };
  const insight = body.results?.[0];
  if (!insight) {
    throw new Error(`Insight "${shortId}" not found`);
  }

  return {
    shortId,
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
