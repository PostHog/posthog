/**
 * PostHog product classification for MCP `exec` sub-tools.
 *
 * The PostHog MCP exposes a single `exec` dispatcher whose `call <sub-tool> …`
 * verb invokes a concrete resource tool (e.g. `experiment-list`,
 * `feature-flag-update`, `execute-sql`, `query-trends`). The sub-tool name is
 * `<domain>-<action>` (or `query-<type>`), and the domain identifies which
 * PostHog product the call touched.
 *
 * `classifyPostHogSubTool` turns a sub-tool name into a stable product id so the
 * agent can report, per turn, which products an answer was grounded in. This is
 * the single source of truth for the product id → label set; the renderer maps
 * ids to icons/styling for display.
 */

/** Canonical PostHog products, keyed by stable id with a display label. */
export const POSTHOG_PRODUCTS = {
  product_analytics: "Product analytics",
  web_analytics: "Web analytics",
  feature_flags: "Feature flags",
  experiments: "Experiments",
  error_tracking: "Error tracking",
  session_replay: "Session replay",
  surveys: "Surveys",
  llm_analytics: "AI observability",
  data_warehouse: "Data warehouse",
  cdp: "Data pipelines",
  logs: "Logs",
  apm: "APM",
  sql: "SQL",
} as const;

export type PostHogProductId = keyof typeof POSTHOG_PRODUCTS;

/**
 * Domain prefix → product, or `null` for admin/meta/introspection domains we
 * deliberately do not surface (listing projects, reading the activity log,
 * managing tasks, searching docs, …). A sub-tool whose domain is absent here
 * surfaces nothing — every chip in the bar is already a PostHog resource, so a
 * generic "PostHog" fallback chip would be redundant.
 */
const DOMAIN_PRODUCT: Record<string, PostHogProductId | null> = {
  // Experiments
  experiment: "experiments",
  // Feature flags
  "feature-flag": "feature_flags",
  "early-access-feature": "feature_flags",
  "scheduled-changes": "feature_flags",
  // Error tracking
  "error-tracking": "error_tracking",
  // Session replay
  "session-recording": "session_replay",
  "visual-review": "session_replay",
  // Surveys
  survey: "surveys",
  // Session replay (Replay Vision)
  vision: "session_replay",
  // LLM analytics. `llm` covers `llm-total-costs`; `llma` covers the whole
  // `llma-*` family (evaluation, clustering, prompt, sentiment, trace, …) in
  // one token rather than one entry per sub-tool.
  llm: "llm_analytics",
  llma: "llm_analytics",
  "agent-feedback": "llm_analytics",
  // Data warehouse. `external-data` covers sources/schemas/sync-logs.
  "external-data": "data_warehouse",
  "read-data-warehouse-schema": "data_warehouse",
  "read-data-schema": "data_warehouse",
  "batch-export": "data_warehouse",
  // Data pipelines (CDP). `cdp-function` covers `cdp-function-templates` too.
  "cdp-function": "cdp",
  "hog-flows-logs": "cdp",
  "hog-flows-metrics": "cdp",
  workflows: "cdp",
  // Logs / APM
  logs: "logs",
  apm: "apm",
  // SQL
  "execute-sql": "sql",
  // Web analytics
  "web-analytics": "web_analytics",
  // Product analytics
  insight: "product_analytics",
  dashboard: "product_analytics",
  action: "product_analytics",
  cohorts: "product_analytics",
  persons: "product_analytics",
  annotation: "product_analytics",
  "event-definition": "product_analytics",
  "custom-property-definition": "product_analytics",
  endpoint: "product_analytics",
  view: "product_analytics",
  "usage-metrics": "product_analytics",
  subscriptions: "product_analytics",
  alert: "product_analytics",
  notebook: "product_analytics",
  // Admin / meta / introspection — recognized but not surfaced.
  project: null,
  user: null,
  accounts: null,
  integration: null,
  "activity-log": null,
  "advanced-activity-logs": null,
  "approval-policy": null,
  "approval-policies": null,
  "change-request": null,
  "docs-search": null,
  "sdk-doctor": null,
  tasks: null,
  "inbox-reports": null,
  "inbox-source-configs": null,
  "signals-scout-runs": null,
  "signals-scout-scratchpad-search": null,
  comment: null,
};

const KNOWN_DOMAINS = Object.keys(DOMAIN_PRODUCT);

const escapeRe = (s: string): string =>
  s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * One regex per domain: the domain must appear as a complete hyphen-delimited
 * token run anywhere in the sub-tool name, tolerating a plural trailing "s".
 * A single pattern covers `feature-flag-get` (prefix), `create-feature-flag`
 * (verb-first) and `feature-flags-status-retrieve` (plural) — so a new
 * `feature-flags-*` tool needs no entry here. The `(^|-)…($|-)` boundaries keep
 * a domain from matching a partial token, and `s?` matches zero for
 * already-plural domains like `external-data-sources`.
 */
const DOMAIN_PATTERNS: ReadonlyArray<readonly [string, RegExp]> =
  KNOWN_DOMAINS.map(
    (d) => [d, new RegExp(`(^|-)${escapeRe(d)}s?($|-)`)] as const,
  );

/**
 * HogQL/PostHog table name → product. Lets an `execute-sql` call be attributed
 * to the product whose data it reads (e.g. `SELECT count() FROM feature_flags`
 * → Feature flags) instead of a generic "SQL" chip. Keys are EXACT table names
 * (lowercased) — `statsig_feature_flags` does not match `feature_flags`. Tables
 * we can't confidently map are omitted: they contribute nothing, and a query
 * touching no mapped table falls back to the "sql" product.
 */
const TABLE_PRODUCT: Record<string, PostHogProductId> = {
  feature_flags: "feature_flags",
  experiments: "experiments",
  events: "product_analytics",
  person: "product_analytics",
  persons: "product_analytics",
  person_distinct_ids: "product_analytics",
  groups: "product_analytics",
  cohort_people: "product_analytics",
  cohortpeople: "product_analytics",
  sessions: "product_analytics",
  raw_sessions: "product_analytics",
  session_replay_events: "session_replay",
  raw_session_replay_events: "session_replay",
  surveys: "surveys",
  logs: "logs",
};

/**
 * Schemas whose tables are PostHog product tables. A qualified reference is
 * only treated as a PostHog table when its schema is one of these — so a data
 * warehouse table like `stripe.feature_flags` or `my_source.events` is left
 * unmapped and can't be mislabeled as a PostHog product.
 */
const POSTHOG_SCHEMAS = new Set(["system"]);

/**
 * Normalize a FROM/JOIN table reference to the PostHog table name to look up,
 * or `null` if it's qualified with a non-PostHog (e.g. warehouse) schema.
 * Unqualified names pass through as-is; `system.feature_flags` → `feature_flags`.
 */
function normalizePostHogTableRef(ref: string): string | null {
  const parts = ref.toLowerCase().split(".");
  if (parts.length === 1) return parts[0] ?? null;
  const schema = parts[0] ?? "";
  const table = parts[parts.length - 1] ?? "";
  return POSTHOG_SCHEMAS.has(schema) ? table : null;
}

/** Extract PostHog table names referenced after FROM/JOIN in a SQL/HogQL string. */
function extractSqlTables(sql: string): string[] {
  const tables: string[] = [];
  // Match `from`/`join` followed by an optionally back-tick/quoted identifier.
  // Subqueries (`from (`) don't match the identifier class and are skipped;
  // their inner FROM clauses are still picked up by the global scan.
  const re = /\b(?:from|join)\s+(["'`]?)([a-zA-Z_][a-zA-Z0-9_.]*)\1/gi;
  let match: RegExpExecArray | null = re.exec(sql);
  while (match !== null) {
    const ref = match[2];
    if (ref) {
      const table = normalizePostHogTableRef(ref);
      if (table) tables.push(table);
    }
    match = re.exec(sql);
  }
  return tables;
}

/**
 * Map a HogQL/SQL query to the products whose tables it reads. A query can
 * touch several tables, so this returns 0..n products (deduped). Returns an
 * empty array when no referenced table maps to a known product.
 */
export function classifyPostHogSqlQuery(sql: string): PostHogProductId[] {
  const products = new Set<PostHogProductId>();
  for (const table of extractSqlTables(sql)) {
    const product = TABLE_PRODUCT[table];
    if (product) products.add(product);
  }
  return [...products];
}

/**
 * Activity-log `scope` value → product. The activity-log tools are generic
 * audit readers (their own domain is suppressed), but a call scoped to a
 * specific entity type is really about that entity's product. Keys are the
 * PascalCase scope enum values; only scopes that map to a surfaced product are
 * listed — admin/meta scopes (Team, Project, User, Role, Comment, Tag, …) are
 * omitted so a scoped audit read of them surfaces nothing, as before.
 */
const ACTIVITY_SCOPE_PRODUCT: Record<string, PostHogProductId> = {
  FeatureFlag: "feature_flags",
  EarlyAccessFeature: "feature_flags",
  Experiment: "experiments",
  ExperimentHoldout: "experiments",
  ExperimentSavedMetric: "experiments",
  ErrorTrackingIssue: "error_tracking",
  Replay: "session_replay",
  SessionRecordingPlaylist: "session_replay",
  Survey: "surveys",
  LLMTrace: "llm_analytics",
  Evaluation: "llm_analytics",
  DataWarehouseSavedQuery: "data_warehouse",
  ExternalDataSource: "data_warehouse",
  ExternalDataSchema: "data_warehouse",
  BatchExport: "data_warehouse",
  BatchImport: "data_warehouse",
  HogFunction: "cdp",
  HogFlow: "cdp",
  Log: "logs",
  LogsAlertConfiguration: "logs",
  LogsExclusionRule: "logs",
  WebAnalyticsFilterPreset: "web_analytics",
  Insight: "product_analytics",
  Dashboard: "product_analytics",
  DashboardWidget: "product_analytics",
  Cohort: "product_analytics",
  Person: "product_analytics",
  Group: "product_analytics",
  Notebook: "product_analytics",
  Action: "product_analytics",
  EventDefinition: "product_analytics",
  PropertyDefinition: "product_analytics",
  Annotation: "product_analytics",
  Endpoint: "product_analytics",
  EndpointVersion: "product_analytics",
  Subscription: "product_analytics",
  AlertConfiguration: "product_analytics",
  Threshold: "product_analytics",
  AlertSubscription: "product_analytics",
};

/**
 * Attribute an activity-log call to the product(s) of its `scope`/`scopes`
 * argument. Returns an empty array when the body has no recognized scope (so an
 * unscoped or admin-scoped audit read still surfaces nothing).
 */
function classifyPostHogActivityLog(commandText: string): PostHogProductId[] {
  const start = commandText.indexOf("{");
  const end = commandText.lastIndexOf("}");
  if (start === -1 || end <= start) return [];
  let body: unknown;
  try {
    body = JSON.parse(commandText.slice(start, end + 1));
  } catch {
    return [];
  }
  if (!body || typeof body !== "object") return [];
  const scopesField = (body as { scopes?: unknown }).scopes;
  const raw: unknown[] = [
    (body as { scope?: unknown }).scope,
    ...(Array.isArray(scopesField) ? scopesField : []),
  ];
  const products = new Set<PostHogProductId>();
  for (const s of raw) {
    if (typeof s === "string") {
      const product = ACTIVITY_SCOPE_PRODUCT[s];
      if (product) products.add(product);
    }
  }
  return [...products];
}

/* Call shapes classified by their arguments rather than the domain map:
 * `query-<type>` by query type, `execute-sql` by the SQL it runs, activity-log
 * reads by their `scope`. Single source of truth shared by the classifiers and
 * `isUnclassifiedPostHogSubTool`, so a new special case added to one can't be
 * missed by the other. Each takes an already trimmed+lowercased name. */

function isQueryCall(name: string): boolean {
  return name === "query" || name.startsWith("query-");
}

function isExecuteSqlCall(name: string): boolean {
  return name === "execute-sql" || name === "execute_sql";
}

function isActivityLogCall(name: string): boolean {
  return (
    name === "activity-log" ||
    name.startsWith("activity-log-") ||
    name.startsWith("advanced-activity-logs")
  );
}

/**
 * Classify an executed MCP exec `call` into the products it touched. For
 * `execute-sql` the query text is inspected so the call is attributed to the
 * product whose tables it reads (e.g. Feature flags), falling back to the
 * generic "sql" product only when no table maps. Activity-log reads are
 * attributed by their `scope` argument. All other sub-tools resolve to their
 * single domain product (or none, for admin/meta domains).
 *
 * `commandText` is the raw exec command (which embeds the SQL for execute-sql
 * and the scope JSON for activity-log reads).
 */
export function classifyPostHogExecCall(
  subTool: string,
  commandText?: string,
): PostHogProductId[] {
  const name = subTool.trim().toLowerCase();
  if (isExecuteSqlCall(name)) {
    const fromTables = commandText ? classifyPostHogSqlQuery(commandText) : [];
    return fromTables.length > 0 ? fromTables : ["sql"];
  }
  if (isActivityLogCall(name)) {
    return commandText ? classifyPostHogActivityLog(commandText) : [];
  }
  const product = classifyPostHogSubTool(subTool);
  return product ? [product] : [];
}

/** Classify a `query-<type>` sub-tool by its query type. */
function classifyQuery(type: string): PostHogProductId | null {
  if (type.startsWith("error-tracking")) return "error_tracking";
  if (type.startsWith("session-recording")) return "session_replay";
  if (type.startsWith("llm")) return "llm_analytics";
  if (type === "logs") return "logs";
  if (type.startsWith("apm")) return "apm";
  // trends / funnel / retention / lifecycle / stickiness / paths (+ -actors)
  return "product_analytics";
}

/**
 * Map a PostHog MCP `call` sub-tool (e.g. `feature-flag-update`, `query-trends`)
 * to a product id. Returns `null` when the name is empty, or when the domain is
 * one we don't surface — either a known admin/meta domain or an unrecognized
 * one (no point in a generic "PostHog" chip inside a PostHog-resources bar).
 */
export function classifyPostHogSubTool(
  subTool: string,
): PostHogProductId | null {
  const name = subTool.trim().toLowerCase();
  if (!name) return null;

  if (isQueryCall(name)) {
    return classifyQuery(name.slice("query-".length));
  }

  const best = matchDomain(name);
  if (best === null) return null;
  return DOMAIN_PRODUCT[best];
}

/**
 * Best (longest) matching known domain for a sub-tool name, or `null` if none
 * match. Longest wins so `feature-flag` beats a hypothetical `feature` and
 * multi-word domains aren't shadowed by shorter prefixes.
 */
function matchDomain(name: string): string | null {
  let best: string | null = null;
  for (const [domain, re] of DOMAIN_PATTERNS) {
    if (re.test(name)) {
      if (best === null || domain.length > best.length) best = domain;
    }
  }
  return best;
}

/**
 * True when a `call` sub-tool is a PostHog resource call we don't recognize at
 * all: not a query/execute-sql/activity-log call and matching no known domain,
 * so it surfaces no product chip. Distinct from a domain we deliberately
 * suppress (project, docs-search, …), which is recognized and returns `null` on
 * purpose. Lets callers log genuinely-unknown calls so `DOMAIN_PRODUCT` can be
 * expanded deliberately instead of silently dropping them.
 */
export function isUnclassifiedPostHogSubTool(subTool: string): boolean {
  const name = subTool.trim().toLowerCase();
  if (!name) return false;
  if (isQueryCall(name) || isExecuteSqlCall(name) || isActivityLogCall(name)) {
    return false;
  }
  return matchDomain(name) === null;
}
