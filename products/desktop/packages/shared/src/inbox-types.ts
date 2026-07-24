export interface AvailableSuggestedReviewer {
  uuid: string;
  name: string;
  email: string;
  github_login: string;
}

/** Signal record kind (backend `source_type`) for a warehouse-backed inbox source. */
export type SignalRecordKind =
  | "issue"
  | "ticket"
  | "scanner_finding"
  | "feedback"
  | "review"
  | "search_opportunity";

/**
 * A warehouse data source the Self-driving inbox can watch. This is the single source of
 * truth the toggle grid, setup switch, source-type map, DWH connection map, and the
 * `SourceProduct` union derive from — adding a warehouse source is one entry here (plus its
 * backend emitter and, if it uses OAuth, a bespoke setup form). `setup: "dynamic"` renders
 * the generic credential form; the three legacy special-cased flows keep their own key.
 */
export interface ExternalInboxSource {
  /**
   * Backend `source_product` (lowercase). Declared as `string` here so the registry can
   * define the universe: `ExternalInboxSourceProduct` is derived from the literal values
   * in EXTERNAL_INBOX_SOURCES and feeds the `SourceProduct` union.
   */
  product: string;
  /** Display label for the toggle card / filter. */
  label: string;
  /** One-line card description. */
  description: string;
  /** Capitalized DWH `source_type` used to match/create the external data source. */
  dwSourceType: string;
  /** Warehouse table(s) that must be syncing for signals to flow. */
  requiredTables: readonly string[];
  /** Backend signal `source_type` this source emits. */
  recordKind: SignalRecordKind;
  /** Setup flow: the generic dynamic credential form, or a legacy special case. */
  setup: "dynamic" | "github" | "zendesk" | "pganalyze";
}

const ISSUE = "Monitor new issues and updates";
const TICKET = "Monitor incoming support tickets";
const CONVERSATION = "Monitor incoming support conversations";
const ERROR = "Surface new and reopened errors";
const FINDING = "Surface new security and code-quality findings";
const FEEDBACK = "Turn product feedback and feature requests into inputs";
const REVIEW = "Monitor new app and product reviews";
const SEARCH = "Fix pages that rank in Google but lose clicks";

/** Registry of warehouse-backed inbox sources, alphabetical within each category. */
export const EXTERNAL_INBOX_SOURCES = [
  // Issue trackers
  {
    product: "gitea",
    label: "Gitea",
    description: ISSUE,
    dwSourceType: "Gitea",
    requiredTables: ["issues"],
    recordKind: "issue",
    setup: "dynamic",
  },
  {
    product: "github",
    label: "GitHub Issues",
    description: ISSUE,
    dwSourceType: "Github",
    requiredTables: ["issues"],
    recordKind: "issue",
    setup: "github",
  },
  {
    product: "gitlab",
    label: "GitLab",
    description: ISSUE,
    dwSourceType: "GitLab",
    requiredTables: ["issues"],
    recordKind: "issue",
    setup: "dynamic",
  },
  {
    product: "jira",
    label: "Jira",
    description: ISSUE,
    dwSourceType: "Jira",
    requiredTables: ["issues"],
    recordKind: "issue",
    setup: "dynamic",
  },
  {
    product: "linear",
    label: "Linear",
    description: ISSUE,
    dwSourceType: "Linear",
    requiredTables: ["issues"],
    recordKind: "issue",
    setup: "dynamic",
  },
  {
    product: "shortcut",
    label: "Shortcut",
    description: ISSUE,
    dwSourceType: "Shortcut",
    requiredTables: ["stories"],
    recordKind: "issue",
    setup: "dynamic",
  },
  // Error tracking
  {
    product: "bugsnag",
    label: "Bugsnag",
    description: ERROR,
    dwSourceType: "Bugsnag",
    requiredTables: ["errors"],
    recordKind: "issue",
    setup: "dynamic",
  },
  {
    product: "honeybadger",
    label: "Honeybadger",
    description: ERROR,
    dwSourceType: "Honeybadger",
    requiredTables: ["faults"],
    recordKind: "issue",
    setup: "dynamic",
  },
  {
    product: "raygun",
    label: "Raygun",
    description: ERROR,
    dwSourceType: "Raygun",
    requiredTables: ["error_groups"],
    recordKind: "issue",
    setup: "dynamic",
  },
  {
    product: "rollbar",
    label: "Rollbar",
    description: ERROR,
    dwSourceType: "Rollbar",
    requiredTables: ["items"],
    recordKind: "issue",
    setup: "dynamic",
  },
  {
    product: "sentry",
    label: "Sentry",
    description: ERROR,
    dwSourceType: "Sentry",
    requiredTables: ["issues"],
    recordKind: "issue",
    setup: "dynamic",
  },
  // Support / helpdesk
  {
    product: "dixa",
    label: "Dixa",
    description: CONVERSATION,
    dwSourceType: "Dixa",
    requiredTables: ["conversations"],
    recordKind: "ticket",
    setup: "dynamic",
  },
  {
    product: "freshdesk",
    label: "Freshdesk",
    description: TICKET,
    dwSourceType: "Freshdesk",
    requiredTables: ["tickets"],
    recordKind: "ticket",
    setup: "dynamic",
  },
  {
    product: "freshservice",
    label: "Freshservice",
    description: TICKET,
    dwSourceType: "Freshservice",
    requiredTables: ["tickets"],
    recordKind: "ticket",
    setup: "dynamic",
  },
  {
    product: "front",
    label: "Front",
    description: CONVERSATION,
    dwSourceType: "Front",
    requiredTables: ["conversations"],
    recordKind: "ticket",
    setup: "dynamic",
  },
  {
    product: "gorgias",
    label: "Gorgias",
    description: TICKET,
    dwSourceType: "Gorgias",
    requiredTables: ["tickets"],
    recordKind: "ticket",
    setup: "dynamic",
  },
  {
    product: "hubspot",
    label: "HubSpot",
    description: TICKET,
    dwSourceType: "Hubspot",
    requiredTables: ["tickets"],
    recordKind: "ticket",
    setup: "dynamic",
  },
  {
    product: "intercom",
    label: "Intercom",
    description: CONVERSATION,
    dwSourceType: "Intercom",
    requiredTables: ["conversations"],
    recordKind: "ticket",
    setup: "dynamic",
  },
  {
    product: "kustomer",
    label: "Kustomer",
    description: CONVERSATION,
    dwSourceType: "Kustomer",
    requiredTables: ["conversations"],
    recordKind: "ticket",
    setup: "dynamic",
  },
  {
    product: "plain",
    label: "Plain",
    description: CONVERSATION,
    dwSourceType: "Plain",
    requiredTables: ["threads"],
    recordKind: "ticket",
    setup: "dynamic",
  },
  {
    product: "zendesk",
    label: "Zendesk",
    description: TICKET,
    dwSourceType: "Zendesk",
    requiredTables: ["tickets"],
    recordKind: "ticket",
    setup: "zendesk",
  },
  // Database / infra performance
  {
    product: "pganalyze",
    label: "pganalyze",
    description:
      "Postgres performance findings, slow queries, and index recommendations",
    dwSourceType: "PgAnalyze",
    requiredTables: ["issues", "servers"],
    recordKind: "issue",
    setup: "pganalyze",
  },
  // Security scanners
  {
    product: "rapid7_insightvm",
    label: "Rapid7 InsightVM",
    description: FINDING,
    dwSourceType: "Rapid7Insightvm",
    requiredTables: ["vulnerabilities"],
    recordKind: "scanner_finding",
    setup: "dynamic",
  },
  {
    product: "semgrep",
    label: "Semgrep",
    description: FINDING,
    dwSourceType: "Semgrep",
    requiredTables: ["sast_findings"],
    recordKind: "scanner_finding",
    setup: "dynamic",
  },
  {
    product: "snyk",
    label: "Snyk",
    description: FINDING,
    dwSourceType: "Snyk",
    requiredTables: ["issues"],
    recordKind: "scanner_finding",
    setup: "dynamic",
  },
  {
    product: "sonarqube",
    label: "SonarQube",
    description: FINDING,
    dwSourceType: "Sonarqube",
    requiredTables: ["issues"],
    recordKind: "scanner_finding",
    setup: "dynamic",
  },
  // Product feedback / feature requests
  {
    product: "aha",
    label: "Aha",
    description: FEEDBACK,
    dwSourceType: "Aha",
    requiredTables: ["ideas"],
    recordKind: "feedback",
    setup: "dynamic",
  },
  {
    product: "asknicely",
    label: "AskNicely",
    description: FEEDBACK,
    dwSourceType: "Asknicely",
    requiredTables: ["responses"],
    recordKind: "feedback",
    setup: "dynamic",
  },
  {
    product: "canny",
    label: "Canny",
    description: FEEDBACK,
    dwSourceType: "Canny",
    requiredTables: ["posts"],
    recordKind: "feedback",
    setup: "dynamic",
  },
  {
    product: "featurebase",
    label: "Featurebase",
    description: FEEDBACK,
    dwSourceType: "Featurebase",
    requiredTables: ["posts"],
    recordKind: "feedback",
    setup: "dynamic",
  },
  {
    product: "frill",
    label: "Frill",
    description: FEEDBACK,
    dwSourceType: "Frill",
    requiredTables: ["ideas"],
    recordKind: "feedback",
    setup: "dynamic",
  },
  {
    product: "productboard",
    label: "Productboard",
    description: FEEDBACK,
    dwSourceType: "Productboard",
    requiredTables: ["notes"],
    recordKind: "feedback",
    setup: "dynamic",
  },
  {
    product: "retently",
    label: "Retently",
    description: FEEDBACK,
    dwSourceType: "Retently",
    requiredTables: ["feedback"],
    recordKind: "feedback",
    setup: "dynamic",
  },
  {
    product: "uservoice",
    label: "UserVoice",
    description: FEEDBACK,
    dwSourceType: "Uservoice",
    requiredTables: ["suggestions"],
    recordKind: "feedback",
    setup: "dynamic",
  },
  // Reviews
  {
    product: "appfigures",
    label: "Appfigures",
    description: REVIEW,
    dwSourceType: "Appfigures",
    requiredTables: ["reviews"],
    recordKind: "review",
    setup: "dynamic",
  },
  {
    product: "appfollow",
    label: "AppFollow",
    description: REVIEW,
    dwSourceType: "Appfollow",
    requiredTables: ["reviews"],
    recordKind: "review",
    setup: "dynamic",
  },
  {
    product: "judgeme_reviews",
    label: "Judge.me",
    description: REVIEW,
    dwSourceType: "JudgeMeReviews",
    requiredTables: ["reviews"],
    recordKind: "review",
    setup: "dynamic",
  },
  // Search analytics
  {
    product: "google_search_console",
    label: "Google Search Console",
    description: SEARCH,
    dwSourceType: "GoogleSearchConsole",
    requiredTables: ["search_analytics_by_query_page"],
    recordKind: "search_opportunity",
    setup: "dynamic",
  },
] as const satisfies readonly ExternalInboxSource[];

/** Warehouse-backed source products, derived from the registry above. */
export type ExternalInboxSourceProduct =
  (typeof EXTERNAL_INBOX_SOURCES)[number]["product"];

/**
 * Every backend `source_product`: the PostHog-native products (alphabetical) plus every
 * warehouse source in EXTERNAL_INBOX_SOURCES.
 */
export type SourceProduct =
  | "conversations"
  | "error_tracking"
  | "health_checks"
  | "llm_analytics"
  | "session_replay"
  | "signals_scout"
  | ExternalInboxSourceProduct;

/**
 * Products that render as a toggle in the Self-driving sources modal. Excludes non-toggle
 * products (`llm_analytics`, `signals_scout`) that appear only as signal origins.
 */
export type ToggleableSourceProduct = Exclude<
  SourceProduct,
  "llm_analytics" | "signals_scout"
>;

/**
 * Every backend signal `source_type`: the PostHog-native types (alphabetical) plus the
 * warehouse record kinds.
 */
export type SourceType =
  | "cross_source_issue"
  | "evaluation"
  | "health_issue"
  | "issue_created"
  | "issue_reopened"
  | "issue_spiking"
  | "session_analysis_cluster"
  | SignalRecordKind;

/**
 * Issue-like records mutate (status/votes change), so their table needs full-refresh sync.
 * Tickets and search-analytics rows are append-only — existing rows never change once written —
 * so they sync incrementally.
 */
export function sourceNeedsFullRefresh(recordKind: SignalRecordKind): boolean {
  return recordKind !== "ticket" && recordKind !== "search_opportunity";
}

export const EXTERNAL_INBOX_SOURCE_BY_PRODUCT: Partial<
  Record<SourceProduct, ExternalInboxSource>
> = Object.fromEntries(EXTERNAL_INBOX_SOURCES.map((s) => [s.product, s]));
