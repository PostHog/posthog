// Wire shapes mirroring the PostHog Cloud REST serializers (Django app
// `agent_platform`). Field names stay snake_case to match the JSON exactly.

export type AgentSessionState =
  | "queued"
  | "running"
  | "completed"
  | "closed"
  | "cancelled"
  | "failed";

export type AgentSessionPrincipalKind =
  | "anonymous"
  | "service"
  | "internal"
  | "shared_secret"
  | "slack";

export type AgentRevisionState = "draft" | "ready" | "live" | "archived";

export type AgentApprovalRequestState =
  | "queued"
  | "approving"
  | "dispatched"
  | "dispatched_failed"
  | "rejected"
  | "expired";

export type AgentApprovalDecision = "approve" | "reject";

/** Resolved creator (from `created_by_id`), or null if unset/deleted. */
export interface AgentApplicationCreator {
  id?: number;
  first_name?: string;
  email?: string;
}

export interface AgentApplication {
  id: string;
  team_id: number;
  name: string;
  /** Globally-unique URL identifier; server-minted unless explicitly allowed. */
  slug?: string;
  description?: string;
  live_revision: string | null;
  archived?: boolean;
  archived_at: string | null;
  created_by_id: number | null;
  created_by: AgentApplicationCreator | null;
  created_at: string;
  updated_at: string;
  /** Slack Event Subscriptions request URL; null without a public ingress URL. */
  slack_events_url: string | null;
  /** Slack Interactivity request URL; null without a public ingress URL. */
  slack_interactivity_url: string | null;
  /** Mode-aware base URL the agent's trigger routes hang off; null without ingress. */
  ingress_base_url: string | null;
}

export type AgentReasoningEffort =
  | "minimal"
  | "low"
  | "medium"
  | "high"
  | "xhigh";

export type AgentModelLevel = "low" | "medium" | "high";

/**
 * Session model stability vs. resilience. `cost` (default): pin the first served
 * model for the whole session — warm prompt cache, no cross-model failover.
 * `availability`: lead with the last-served model but fail over on failure.
 * Mirrors `spec.models.optimize_for` in the backend.
 */
export type AgentModelOptimizeFor = "cost" | "availability";

/** One model in a manual policy: a canonical model id (e.g.
 *  `anthropic/claude-sonnet-4-6`) plus an optional per-model reasoning override. */
export interface AgentModelEntry {
  model: string;
  reasoning?: AgentReasoningEffort;
}

/**
 * How a revision picks its model. `auto` resolves a maintained, priority-ordered,
 * cross-provider list from `level` at runtime; `manual` pins an author-ordered
 * fallback list (primary first). Mirrors `spec.models` in the backend.
 */
export type AgentModelPolicy =
  | {
      mode: "auto";
      level?: AgentModelLevel;
      reasoning?: AgentReasoningEffort;
      optimize_for?: AgentModelOptimizeFor;
    }
  | {
      mode: "manual";
      models: AgentModelEntry[];
      optimize_for?: AgentModelOptimizeFor;
    };

/**
 * A served model + its cost profile, as the model browser shows it. Mirrors the
 * ai-gateway catalog (`@posthog/agent-applications-models`). Pricing is USD per
 * million tokens.
 */
export interface ModelCatalogEntry {
  /** Canonical id, e.g. `anthropic/claude-sonnet-4.6`. */
  model: string;
  provider: string;
  context_window: number;
  input: number;
  output: number;
  cacheRead?: number;
  cacheWrite?: number;
}

/** The full served catalog plus the curated `auto` level → model mapping. */
export interface ModelCatalog {
  models: ModelCatalogEntry[];
  /** Canonical ids each auto level resolves to, in priority order. */
  levels: Record<AgentModelLevel, string[]>;
}

/**
 * The agent spec carried on a revision. Known top-level fields are surfaced and
 * the rest passes through pending fully-typed elaboration.
 */
export interface AgentSpec {
  /** Model selection. `model` is the legacy single-string form; current specs
   *  carry `models`. One or the other is present. */
  models?: AgentModelPolicy;
  model?: string;
  triggers?: unknown[];
  tools?: unknown[];
  mcps?: unknown[];
  skills?: unknown[];
  secrets?: string[];
  limits?: {
    max_turns?: number;
    max_tool_calls?: number;
    max_wall_seconds?: number;
  };
  reasoning?: AgentReasoningEffort;
  [key: string]: unknown;
}

export interface AgentRevision {
  id: string;
  application: string;
  parent_revision?: string | null;
  state: AgentRevisionState;
  bundle_uri?: string;
  bundle_sha256: string | null;
  spec?: AgentSpec;
  created_by_id: number | null;
  created_by: AgentApplicationCreator | null;
  created_at: string;
  updated_at: string;
}

// `…/agent_applications/{id}/preview-token/?revision_id=<uuid>` mints a
// short-lived HS256 JWT that authorizes the ingress to route /run /send /listen
// /cancel against a non-live revision. Sent on those calls via the
// `X-Agent-Preview-Token` header (or `?preview_token=` query for EventSource),
// alongside the usual PostHog bearer. The response's `endpoints` carry the
// per-trigger preview URLs to hit directly, so the client never derives a
// revision-scoped ingress URL by string-mangling `application.ingress_base_url`.

/** Per-trigger preview URLs, keyed by trigger type → action → absolute URL. */
export type AgentPreviewEndpoints = Record<string, Record<string, string>>;

export interface AgentPreviewToken {
  /** HS256 JWT bound to (app, revision). Short TTL. */
  token: string;
  /** Token TTL in seconds from issue; mint a fresh one before this elapses. */
  expires_in: number;
  /** `<application_slug>-<revision_uuid_hex>` — the slug ingress uses in routing. */
  ingress_slug: string;
  /**
   * Per-trigger ingress URLs derived from this revision's `spec.triggers[]`.
   * Empty when no public agent-ingress URL is configured for the active routing mode.
   * Shape: `{ chat: { run, send, listen, cancel, client_tool_result }, slack: {...} }`.
   */
  endpoints: AgentPreviewEndpoints;
  /** Header/query names + per-trigger accepted auth modes. Opaque to most callers. */
  auth: Record<string, unknown>;
  /** Server-side proxy alternative — opaque shape; preferred path is direct-to-ingress. */
  preview_proxy: Record<string, unknown>;
}

// `…/revisions/{id}/bundle/` returns a typed bundle ({ agent_md, skills, tools });
// the client flattens it into these per-file rows keyed by canonical path
// (agent.md, skills/<id>/SKILL.md, tools/<id>/source.ts, tools/<id>/schema.json).

export type BundleFileLanguage = "markdown" | "typescript" | "json" | "text";

export interface BundleFile {
  path: string;
  content: string;
  language: BundleFileLanguage;
}

// Custom-tool authoring on a draft revision (`agent_platform`): compile-on-save
// (PUT …/tools/{id}), delete, and dry-run (POST …/tools/{id}/dry_run). Draft-only
// for writes — ready/live/archived bundles are sealed.

/** Discriminator for a custom-tool compile failure. Mirrors the backend AST/
 *  transform checks; a failed compile returns one or more of these. */
export type ToolCompileErrorKind =
  | "parse_failed"
  | "ast_no_default_export"
  | "ast_default_not_object"
  | "ast_missing_actions"
  | "ast_actions_not_object"
  | "ast_missing_default_action"
  | "ast_default_action_not_callable"
  | "ast_dynamic_export"
  | "transform_failed";

/** One diagnostic from a failed tool compile. `line`/`column` are 1-based. */
export interface ToolCompileError {
  kind: ToolCompileErrorKind;
  message: string;
  line?: number;
  column?: number;
}

/** Static capabilities the compiler extracted from a tool's source. */
export interface ToolCapabilities {
  /** Secret names the tool references via `ctx.secrets.ref("NAME")`. */
  secret_refs: string[];
  /** True when the tool derives secret names dynamically (can't be enumerated). */
  dynamic_secret_refs: boolean;
}

/** Body for PUT …/tools/{toolId} — author/compile a tool. */
export interface WriteToolRequest {
  description: string;
  args_schema: Record<string, unknown>;
  source: string;
}

/**
 * Outcome of a tool write. A compile failure (HTTP 422) is a first-class result,
 * NOT a thrown error, so the caller renders `errors` inline against the source.
 * Other non-2xx (400 invalid_request, 409 sealed revision, …) still throw.
 */
export type WriteToolResult =
  | { ok: true; tool_id: string; capabilities: ToolCapabilities }
  | {
      ok: false;
      error: "tool_compile_failed";
      tool_id: string;
      errors: ToolCompileError[];
    };

/** Body for POST …/tools/{toolId}/dry_run. */
export interface DryRunToolRequest {
  /** Free-form JSON passed to the tool's `actions.default`; NOT validated
   *  against `args_schema` (the author's responsibility). */
  args: unknown;
  /** `secretName -> placeholder` returned by `ctx.secrets.ref(name)` in the
   *  sandbox; real secret values never leave the backend. */
  mock_secrets?: Record<string, string>;
}

/**
 * The dry-run response envelope (returned on HTTP 200 AND 500). A tool-side
 * failure is an HTTP 200 with `ok: false` — read `ok` from HERE, not the status.
 */
export interface DryRunToolEnvelope {
  ok: boolean;
  tool_id: string;
  result?: unknown;
  /** `error.code` is one of sandbox_acquire_failed | sandbox_invoke_failed |
   *  timeout | secret_not_provisioned | action_not_found | tool_not_found |
   *  dry_run_unknown. */
  error?: { code: string; message: string };
  duration_ms: number;
}

/**
 * A dry-run outcome. `throttled` (HTTP 429) and `unavailable` (HTTP 503) are
 * distinct interactive states — surfaced as data, never thrown, and never
 * retried (dry-run is process-capped).
 */
export type DryRunToolResult =
  | { outcome: "completed"; envelope: DryRunToolEnvelope }
  | { outcome: "throttled"; max_concurrent?: number }
  | { outcome: "unavailable" };

// `…/revisions/{id}/slack_manifest/` derives the Slack app manifest from the
// revision's slack trigger + tools (scopes + event subscriptions computed).

export interface AgentSlackManifest {
  revision_id: string;
  /** Opaque Slack app manifest JSON to paste into "create from manifest". */
  manifest: Record<string, unknown>;
  notes: string[];
  events_url: string | null;
  interactivity_url: string | null;
}

// The agent's S3-backed memory store: markdown files (`…/memory/…`) plus the
// JSONL reference tables the @posthog/table-* tools write.

export interface AgentMemoryHeader {
  path: string;
  description: string;
  tags: string[];
  created_at: string | null;
  updated_at: string | null;
}

export interface AgentMemoryFile extends AgentMemoryHeader {
  content: string;
}

/** Pre-aggregated folder tree from `…/memory/tree/`. */
export interface AgentMemoryTreeNode {
  name: string;
  type: "folder" | "file";
  path?: string;
  description?: string;
  tags?: string[];
  children?: AgentMemoryTreeNode[];
}

export interface AgentMemorySearchResult {
  path: string;
  description: string;
  tags: string[];
  score: number;
  snippet?: string | null;
}

export interface AgentMemoryTableHeader {
  name: string;
  size: number;
}

export interface AgentMemoryTableRows {
  name: string;
  total: number;
  returned: number;
  limit: number;
  rows: Record<string, unknown>[];
}

// The agent's end-users and their linked external identities. `agent_user` is
// the stable per-principal identity (a Slack user, a JWT `sub`, a PostHog user);
// `agent_identity_credential` is a durable OAuth link that user established so
// the agent can act AS them on an external system. The API exposes connection
// *metadata only* — encrypted tokens are NEVER serialized to the client.

/** A linked external identity for an agent user. Credential material is omitted. */
export interface AgentUserConnection {
  id: string;
  provider: string;
  /** Granted scopes (plaintext; no secret material). */
  scopes: string[];
  /** `active` once linked; `revoked` after a disconnect (kept for audit). */
  state: "active" | "revoked";
  /** Proven external subject (e.g. a PostHog user uuid) for identity-establishing
   *  providers; null for API-only links. */
  subject: string | null;
  /** When the access token expires, if the provider issues expiring tokens. */
  access_expires_at: string | null;
  created_at: string;
  updated_at: string;
  revoked_at: string | null;
}

/** An agent end-user (`agent_user`) plus their linked connections. */
export interface AgentUserWithConnections {
  id: string;
  /** Edge-identity kind: `slack` | `jwt` | `posthog` | `service` | … */
  principal_kind: string;
  /** Stable principal id within that kind (Slack user id, JWT `sub`, …). */
  principal_id: string;
  /** Optional trigger-stamped context (e.g. Slack workspace/display name). */
  metadata?: Record<string, unknown>;
  created_at: string;
  connections: AgentUserConnection[];
}

export interface AgentUsersListResponse {
  results: AgentUserWithConnections[];
  count: number;
}

export interface AgentSessionUsageTotal {
  tokens_in: number;
  tokens_out: number;
  cache_read: number;
  cache_write: number;
  cost_input: number;
  cost_output: number;
  cost_cache_read: number;
  cost_cache_write: number;
  cost_total: number;
}

export interface AgentSessionPrincipal {
  kind: AgentSessionPrincipalKind;
  /** Stable principal id (PAT id, slack user id, …); absent for anonymous. */
  id?: string;
  team_id?: number;
}

/** Trigger-specific metadata stamped at session creation; shape varies by kind. */
export type AgentSessionTriggerMetadata = Record<string, unknown>;

export interface AgentSessionSummary {
  id: string;
  application_id: string;
  revision_id: string;
  state: AgentSessionState;
  external_key: string | null;
  trigger_metadata?: AgentSessionTriggerMetadata | null;
  principal: AgentSessionPrincipal | null;
  /** Count of messages in the conversation. */
  turns: number;
  /** Last assistant text (~120 chars); null before any assistant turn. */
  preview: string | null;
  usage_total: AgentSessionUsageTotal;
  retry_count: number;
  created_at: string;
  updated_at: string;
}

export interface AgentApplicationSessionsListResponse {
  results: AgentSessionSummary[];
  count: number;
}

// Stored conversation shape on a session: the runtime persists pi-ai's
// `conversation` array. Part shapes mirror what the agent-console apiClient
// narrows (text/thinking/toolCall for assistants; text/image for users; text
// for tool results).

export interface AgentTextPart {
  type: "text";
  text: string;
}

export interface AgentThinkingPart {
  type: "thinking";
  thinking: string;
}

export interface AgentImagePart {
  type: "image";
  [key: string]: unknown;
}

export interface AgentToolCallPart {
  type: "toolCall";
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export type AgentAssistantContentPart =
  | AgentTextPart
  | AgentThinkingPart
  | AgentToolCallPart;

export type AgentUserContentPart = AgentTextPart | AgentImagePart;

export interface AgentConversationUserMessage {
  role: "user";
  /** String shorthand, or an array of text/image parts. */
  content: string | AgentUserContentPart[];
  /** Epoch milliseconds. */
  timestamp: number;
}

export interface AgentConversationAssistantMessage {
  role: "assistant";
  /** Array of text/thinking/toolCall parts. */
  content: AgentAssistantContentPart[];
  timestamp: number;
  api?: string;
  provider?: string;
  model?: string;
  usage?: Record<string, unknown>;
  stopReason?: string;
  errorMessage?: string;
}

export interface AgentConversationToolResultMessage {
  /** Wire value is `toolResult` (NOT `tool`) — matches the runtime serializer. */
  role: "toolResult";
  toolCallId: string;
  toolName: string;
  /** Array of text parts (image parts are dropped on render). */
  content: AgentTextPart[];
  isError: boolean;
  timestamp: number;
}

export type AgentConversationMessage =
  | AgentConversationUserMessage
  | AgentConversationAssistantMessage
  | AgentConversationToolResultMessage;

export interface AgentApplicationSessionDetail {
  id: string;
  application_id: string;
  revision_id: string;
  team_id: number;
  state: AgentSessionState;
  external_key: string | null;
  trigger_metadata?: AgentSessionTriggerMetadata | null;
  principal: AgentSessionPrincipal | null;
  usage_total: AgentSessionUsageTotal;
  conversation: AgentConversationMessage[];
  /** Messages that arrived while a turn was in flight. */
  pending_inputs: AgentConversationMessage[];
  retry_count: number;
  created_at: string;
  updated_at: string;
  /** True when `last_n` was supplied AND the full conversation exceeded it. */
  conversation_trimmed: boolean;
  /** Total messages in the untrimmed conversation; present only when trimmed. */
  conversation_total_turns?: number;
}

// `…/sessions/{id}/logs/` returns rows from the shared ClickHouse `log_entries`
// table via `fetch_log_entries` — the same flat shape hog_function logs use.

export type AgentLogLevel = "DEBUG" | "LOG" | "INFO" | "WARN" | "ERROR";

export interface AgentSessionLogEntry {
  log_source_id: string;
  instance_id: string;
  /** ISO timestamp. */
  timestamp: string;
  /** One of AgentLogLevel, but server may emit other casings — keep it open. */
  level: string;
  message: string;
}

export interface AgentSessionLogsParams {
  limit?: number;
  /** Comma-separated levels server-side; pass an array, joined by the client. */
  level?: AgentLogLevel[];
  search?: string;
  after?: string;
  before?: string;
}

export interface AgentFleetLiveSessionSummary {
  id: string;
  application_id: string;
  revision_id: string;
  team_id: number;
  state: AgentSessionState;
  external_key: string | null;
  trigger_metadata?: AgentSessionTriggerMetadata | null;
  principal: AgentSessionPrincipal | null;
  turns: number;
  preview: string | null;
  usage_total: AgentSessionUsageTotal;
  created_at: string;
  updated_at: string;
}

export interface AgentFleetLiveSessionsResponse {
  results: AgentFleetLiveSessionSummary[];
}

/**
 * Who clears a gated call. `principal` = the session's own principal decides at
 * the ingress (generic identity match); `agent` = the owning team's admins
 * decide in the console. Mirrors `ApprovalType` in agent-shared `spec.ts`.
 */
export type AgentApprovalType = "principal" | "agent";

/** Resolved approval policy stamped on the request at queue time. */
export interface AgentApproverScope {
  type: AgentApprovalType;
  allow_edit: boolean;
}

export interface AgentApprovalRequest {
  id: string;
  session_id: string;
  application_id: string;
  team_id: number;
  revision_id: string;
  turn: number;
  tool_call_id: string;
  tool_name: string;
  proposed_args: Record<string, unknown>;
  decided_args: Record<string, unknown> | null;
  assistant_message: Record<string, unknown>;
  approver_scope: AgentApproverScope;
  state: AgentApprovalRequestState;
  decision_by: string | null;
  decision_at: string | null;
  decision_reason: string | null;
  dispatch_outcome: Record<string, unknown> | null;
  created_at: string;
  expires_at: string;
}

/** Body for POST …/approvals/{id}/decide/. */
export interface DecideApprovalRequest {
  decision: AgentApprovalDecision;
  /** Honoured only when the tool's approval_policy.allow_edit is true. */
  edited_args?: Record<string, unknown>;
  reason?: string;
}

export interface AgentSessionsListParams {
  limit?: number;
  offset?: number;
  /** Comma-separated states accepted server-side; pass an array, joined by the client. */
  state?: AgentSessionState[];
  revision_id?: string;
  /** Restrict to sessions started by this agent user (`agent_user.id`). */
  agent_user_id?: string;
  created_after?: string;
  created_before?: string;
  /** Case-insensitive server-side match over the conversation text, id, and external key. */
  search?: string;
}

export interface AgentApprovalsListParams {
  state?: AgentApprovalRequestState;
  agent_id?: string;
  limit?: number;
  offset?: number;
}

// Live session events from the chat trigger's `/listen` endpoint (SSE
// `text/event-stream` JSON frames). The `kind` discriminator and `data`
// payloads come from `agent-ingress/src/triggers/chat.ts` +
// `agent-runner/src/loop/bus.ts`.

interface AgentSessionEventBase {
  session_id: string;
  /** ISO timestamp the runner stamped on the frame. */
  ts: string;
}

/** Session accepted and the runner started — `{ team_id, agent, rev }`. */
export type AgentSessionStartedEvent = AgentSessionEventBase & {
  kind: "session_started";
  data: { team_id?: number; agent?: string; rev?: string };
};

/** Server-confirmed user message, echoed when drained from `pending_inputs`. */
export type AgentUserMessageEvent = AgentSessionEventBase & {
  kind: "user_message";
  data: { text: string; timestamp?: string };
};

/** A new assistant turn began — `{ turn }` is the turn index. */
export type AgentTurnStartedEvent = AgentSessionEventBase & {
  kind: "turn_started";
  data: { turn?: number };
};

/** Streaming assistant text fragment. */
export type AgentAssistantTextDeltaEvent = AgentSessionEventBase & {
  kind: "assistant_text_delta";
  data: { turn?: number; text: string };
};

/** Streaming assistant thinking fragment. */
export type AgentAssistantThinkingDeltaEvent = AgentSessionEventBase & {
  kind: "assistant_thinking_delta";
  data: { turn?: number; thinking: string };
};

/** A tool call appeared (name known, args still streaming). */
export type AgentToolCallStartEvent = AgentSessionEventBase & {
  kind: "tool_call_start";
  data: { turn?: number; id: string; name: string };
};

/** Incremental tool-call args — string fragment or partial object. */
export type AgentToolCallArgsDeltaEvent = AgentSessionEventBase & {
  kind: "tool_call_args_delta";
  data: { turn?: number; id: string; argsDelta: unknown };
};

/** Turn-end snapshot of the full assistant text (deltas already filled it). */
export type AgentAssistantTextEvent = AgentSessionEventBase & {
  kind: "assistant_text";
  data: { text: string };
};

/** Canonical tool call with finalized args. */
export type AgentToolCallEvent = AgentSessionEventBase & {
  kind: "tool_call";
  data: { id: string; name: string; args?: Record<string, unknown> };
};

/** Tool result — `ok` plus `output` on success, `error` on failure. */
export type AgentToolResultEvent = AgentSessionEventBase & {
  kind: "tool_result";
  data: {
    id: string;
    tool?: string;
    ok?: boolean;
    output?: unknown;
    error?: string;
    /**
     * Present when this result is an approval-gated call's synthetic outcome.
     * `state: "queued"` means it's awaiting a decision — the chat service keys
     * the inline approval card off it (then one-shot-fetches the full request).
     * A later result with the same `request_id` and a non-queued state clears
     * the card. `allow_edit` + `approver_scope` mirror the persisted envelope.
     */
    approval?: {
      request_id: string;
      state: string;
      allow_edit?: boolean;
      approver_scope?: AgentApproverScope;
    };
  };
};

/** Turn finished; session stays open for more input. */
export type AgentCompletedEvent = AgentSessionEventBase & {
  kind: "completed";
  data: { turns?: number; summary?: unknown };
};

/** Session parked for a steering message (`@posthog/meta-ask-for-input`). */
export type AgentWaitingEvent = AgentSessionEventBase & {
  kind: "waiting";
  data: { turns?: number; prompt?: string };
};

/** Terminal failure — `reason` is for owners/logs, not end users. */
export type AgentFailedEvent = AgentSessionEventBase & {
  kind: "failed";
  data: { reason?: string; turns?: number };
};

/** Session sealed (terminal); no further `/send`s accepted. */
export type AgentClosedEvent = AgentSessionEventBase & {
  kind: "closed";
  data: Record<string, unknown>;
};

/** Model invoked a client-fulfilled tool; the host runs it and posts back. */
export type AgentClientToolCallEvent = AgentSessionEventBase & {
  kind: "client_tool_call";
  data: { call_id: string; tool_id: string; args?: Record<string, unknown> };
};

/** A client tool's outcome landed (sync POST or interactive `/send` wake). */
export type AgentClientToolResultEvent = AgentSessionEventBase & {
  kind: "client_tool_result";
  data: { call_id: string; result?: unknown; error?: string };
};

/**
 * Draft-preview only. Server fires this on `/listen` ~5s before the preview
 * token expires (then closes the stream); the client mints a fresh token and
 * reconnects. The kind alone is the signal — `data` is unused.
 */
export type AgentPreviewTokenRequiredEvent = AgentSessionEventBase & {
  kind: "preview_token_required";
  data: Record<string, unknown>;
};

export type AgentSessionEvent =
  | AgentSessionStartedEvent
  | AgentUserMessageEvent
  | AgentTurnStartedEvent
  | AgentAssistantTextDeltaEvent
  | AgentAssistantThinkingDeltaEvent
  | AgentToolCallStartEvent
  | AgentToolCallArgsDeltaEvent
  | AgentAssistantTextEvent
  | AgentToolCallEvent
  | AgentToolResultEvent
  | AgentCompletedEvent
  | AgentWaitingEvent
  | AgentFailedEvent
  | AgentClosedEvent
  | AgentClientToolCallEvent
  | AgentClientToolResultEvent
  | AgentPreviewTokenRequiredEvent;

/** Discriminator values for {@link AgentSessionEvent}. */
export type AgentSessionEventKind = AgentSessionEvent["kind"];

// The runner captures `$ai_*` observability events into the team's OWN PostHog
// project (tagged `$ai_origin = 'agent_platform_runner'`, `$agent_application_id`);
// the observability surface rolls those up via HogQL. These are the *derived*
// analytics shapes the client produces from raw HogQL grids — not a backend wire
// serializer — but live here so UI hooks import them alongside the other types.

export interface AgentAnalyticsKpis {
  spendUsd: number;
  sessions: number;
  /** 0..1 — share of generations that errored. */
  failureRate: number;
  /** p95 model latency, seconds. */
  p95LatencyS: number;
}

export interface AgentAnalyticsDaily {
  /** Short date labels, oldest → newest (14 days). */
  labels: string[];
  spend: number[];
  sessions: number[];
  /** 0..1 per day. */
  failureRate: number[];
}

export interface AgentAnalyticsDeltas {
  /** Percent change vs the prior 7 days (e.g. 12 = +12%). `null` when undefined. */
  spend: number | null;
  sessions: number | null;
  /** Change in failure rate, in percentage points. `null` when undefined. */
  failureRatePoints: number | null;
}

export interface AgentAnalyticsAgentRow {
  id: string;
  name: string;
  sessions: number;
  spendUsd: number;
  failureRate: number;
  p95LatencyS: number;
  tokens: number;
}

export interface AgentAnalyticsModelRow {
  model: string;
  spendUsd: number;
  calls: number;
}

export interface AgentAnalyticsToolRow {
  tool: string;
  calls: number;
  errors: number;
  errorRate: number;
}

export interface AgentAnalyticsData {
  kpis: AgentAnalyticsKpis;
  daily: AgentAnalyticsDaily;
  deltas: AgentAnalyticsDeltas;
  byAgent: AgentAnalyticsAgentRow[];
  byModel: AgentAnalyticsModelRow[];
  toolErrors: AgentAnalyticsToolRow[];
  /** True when there is no agent AI activity in the window — drives the empty state. */
  empty: boolean;
}
