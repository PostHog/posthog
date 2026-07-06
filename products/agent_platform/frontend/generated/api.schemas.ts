/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * Resolved creator (id, first_name, email) from `created_by_id`, or null if unset or the user was deleted.
 * @nullable
 */
export type AgentApplicationApiCreatedBy = {
    readonly id?: number
    readonly first_name?: string
    readonly email?: string
} | null

export interface AgentApplicationApi {
    readonly id: string
    readonly team_id: number
    /** @maxLength 255 */
    name: string
    /**
     * Globally-unique URL identifier. Server-minted as an opaque random slug on create; only allowlisted first-party teams may set it explicitly. Slugs live in one global namespace (domain-mode ingress routing carries no team).
     * @maxLength 63
     * @pattern ^[-a-zA-Z0-9_]+$
     */
    slug?: string
    description?: string
    /** @nullable */
    readonly live_revision: string | null
    archived?: boolean
    /** @nullable */
    readonly archived_at: string | null
    /** @nullable */
    readonly created_by_id: number | null
    /**
     * Resolved creator (id, first_name, email) from `created_by_id`, or null if unset or the user was deleted.
     * @nullable
     */
    readonly created_by: AgentApplicationApiCreatedBy
    readonly created_at: string
    readonly updated_at: string
    /**
     * Public URL to paste into the Slack app dashboard under Event Subscriptions → Request URL. Computed from the agent slug and the deployment's ingress routing mode (`AGENT_INGRESS_DOMAIN_SUFFIX` in domain mode, `AGENT_INGRESS_PUBLIC_URL` in path mode). Null when no public agent-ingress URL is configured (e.g. local dev without a tunnel).
     * @nullable
     */
    readonly slack_events_url: string | null
    /**
     * Public URL to paste into the Slack app dashboard under Interactivity & Shortcuts → Request URL. Same source + null behaviour as `slack_events_url`.
     * @nullable
     */
    readonly slack_interactivity_url: string | null
    /**
     * Mode-aware base URL the agent's trigger routes hang off — append `/webhook`, `/run`, `/mcp`, etc. Domain mode: `https://<slug><suffix>`; path mode: `<public_url>/agents/<slug>`. Same source + null behaviour as `slack_events_url` (null when no public ingress URL is configured).
     * @nullable
     */
    readonly ingress_base_url: string | null
}

export interface PaginatedAgentApplicationListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AgentApplicationApi[]
}

export interface AgentMemoryHeaderApi {
    /** Relative path within the agent's memory, e.g. 'incidents/db.md'. */
    path: string
    /** One-line summary from the file's frontmatter. */
    description: string
    /** Frontmatter tags (lowercase a-z 0-9 _ - only). */
    tags: string[]
    /**
     * ISO-8601 timestamp stamped on create. Null for files written before this field was introduced.
     * @nullable
     */
    created_at: string | null
    /**
     * ISO-8601 timestamp stamped on every write.
     * @nullable
     */
    updated_at: string | null
}

export interface AgentMemoryListResponseApi {
    /** Number of entries returned. */
    count: number
    /** Headers (frontmatter only) — no file bodies. Use the read endpoint for the body. */
    entries: AgentMemoryHeaderApi[]
}

/**
 * Body shape for AgentMemoryViewSet.write_file (create).
 */
export interface AgentMemoryWriteRequestApi {
    /** Where to store the file. Lowercase a-z 0-9 _ - / only, must end in .md. */
    path: string
    /**
     * One-line summary, max 280 chars. Surfaces in list/search results.
     * @maxLength 280
     */
    description: string
    /** Full markdown body. */
    content: string
    /** Optional flat tags for search ranking. Lowercase a-z 0-9 _ - only. */
    tags?: string[]
}

export interface AgentMemoryFileApi {
    /** Full markdown body. */
    content: string
}

/**
 * Body shape for AgentMemoryViewSet.update_file. Omitted fields preserve the existing value.
 */
export interface PatchedAgentMemoryUpdateRequestApi {
    /** @maxLength 280 */
    description?: string
    content?: string
    tags?: string[]
}

export interface AgentMemorySearchResultApi {
    path: string
    description: string
    tags: string[]
    /** BM25 relevance score. */
    score: number
    /**
     * Body snippet around the earliest match. Null when only the header matched.
     * @nullable
     */
    snippet: string | null
}

export interface AgentMemorySearchResponseApi {
    /** The original search cue, echoed back. */
    cue: string
    count: number
    results: AgentMemorySearchResultApi[]
}

export interface AgentTableHeaderApi {
    /** Table name. */
    name: string
    /** Object size in bytes. */
    size: number
}

export interface AgentTablesListResponseApi {
    /** Number of tables. */
    count: number
    /** Tabular-reference tables for this agent (the @posthog/table-* JSONL tables). */
    tables: AgentTableHeaderApi[]
}

export type AgentTableRowsResponseApiRowsItem = { [key: string]: unknown }

export interface AgentTableRowsResponseApi {
    name: string
    /** Total rows in the table. */
    total: number
    /** Rows in this response (capped by limit). */
    returned: number
    limit: number
    /** The rows (arbitrary JSON objects). */
    rows: AgentTableRowsResponseApiRowsItem[]
}

/**
 * Folder tree rooted at the agent's memory prefix. Each node is {name, type: 'folder'|'file', path?, description?, tags?, children?}.
 */
export type AgentMemoryTreeResponseApiRoot = { [key: string]: unknown }

export interface AgentMemoryTreeResponseApi {
    /** Folder tree rooted at the agent's memory prefix. Each node is {name, type: 'folder'|'file', path?, description?, tags?, children?}. */
    root: AgentMemoryTreeResponseApiRoot
}

/**
 * * `draft` - draft
 * * `ready` - ready
 * * `live` - live
 * * `archived` - archived
 */
export type AgentRevisionStateEnumApi = (typeof AgentRevisionStateEnumApi)[keyof typeof AgentRevisionStateEnumApi]

export const AgentRevisionStateEnumApi = {
    Draft: 'draft',
    Ready: 'ready',
    Live: 'live',
    Archived: 'archived',
} as const

/**
 * One reference to a versioned skill in the llma-skill store, pinned into
 * this agent's bundle at freeze.
 */
export interface SkillRefApi {
    /**
     * Name of the skill in the llma-skill store to pin into this agent. Resolved at freeze to the chosen `version` and materialized into the bundle.
     * @maxLength 64
     */
    from_template: string
    /**
     * Folder the resolved skill is materialized under in the bundle (`skills/<alias>/`). Lowercase letters, digits, hyphens or underscores, starting and ending with a letter or digit; must be unique within the revision.
     * @maxLength 64
     * @pattern ^[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?$
     */
    alias: string
    /**
     * Specific published version to pin. Omit to pin the store's latest version at freeze time.
     * @minimum 1
     */
    version?: number
}

/**
 * Resolved creator (id, first_name, email) from `created_by_id`, or null if unset or the user was deleted.
 * @nullable
 */
export type AgentRevisionApiCreatedBy = {
    readonly id?: number
    readonly first_name?: string
    readonly email?: string
} | null

export interface AgentRevisionApi {
    readonly id: string
    readonly application: string
    /** @nullable */
    parent_revision?: string | null
    readonly state: AgentRevisionStateEnumApi
    /** Storage-prefix metadata for the bundle, e.g. `fs://my-agent/`. Optional — leave blank and the server fills `fs://<application-slug>/`. Bundles are addressed by revision id regardless, so this is only a prefix hint. */
    bundle_uri?: string
    /** @nullable */
    readonly bundle_sha256: string | null
    spec?: unknown
    /** Store-skill references for this draft, set via the `skill_refs` action and resolved into the bundle at freeze. Preserved as the authoring record on the frozen revision (and carried forward when forking a new draft); resolved provenance is stamped onto `spec.skills[].source_version_id`. */
    readonly skill_refs: readonly SkillRefApi[]
    /** @nullable */
    readonly created_by_id: number | null
    /**
     * Resolved creator (id, first_name, email) from `created_by_id`, or null if unset or the user was deleted.
     * @nullable
     */
    readonly created_by: AgentRevisionApiCreatedBy
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedAgentRevisionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AgentRevisionApi[]
}

/**
 * Resolved creator (id, first_name, email) from `created_by_id`, or null if unset or the user was deleted.
 * @nullable
 */
export type PatchedAgentRevisionApiCreatedBy = {
    readonly id?: number
    readonly first_name?: string
    readonly email?: string
} | null

export interface PatchedAgentRevisionApi {
    readonly id?: string
    readonly application?: string
    /** @nullable */
    parent_revision?: string | null
    readonly state?: AgentRevisionStateEnumApi
    /** Storage-prefix metadata for the bundle, e.g. `fs://my-agent/`. Optional — leave blank and the server fills `fs://<application-slug>/`. Bundles are addressed by revision id regardless, so this is only a prefix hint. */
    bundle_uri?: string
    /** @nullable */
    readonly bundle_sha256?: string | null
    spec?: unknown
    /** Store-skill references for this draft, set via the `skill_refs` action and resolved into the bundle at freeze. Preserved as the authoring record on the frozen revision (and carried forward when forking a new draft); resolved provenance is stamped onto `spec.skills[].source_version_id`. */
    readonly skill_refs?: readonly SkillRefApi[]
    /** @nullable */
    readonly created_by_id?: number | null
    /**
     * Resolved creator (id, first_name, email) from `created_by_id`, or null if unset or the user was deleted.
     * @nullable
     */
    readonly created_by?: PatchedAgentRevisionApiCreatedBy
    readonly created_at?: string
    readonly updated_at?: string
}

/**
 * Body shape for PUT /revisions/<id>/agent_md/.
 */
export interface WriteAgentMdRequestApi {
    content: string
}

export type WriteTypedBundleRequestApiSpec = { [key: string]: unknown }

export type WriteToolRequestApiArgsSchema = { [key: string]: unknown }

/**
 * Body shape for PUT /revisions/<id>/tools/<tool_id>/.
 */
export interface WriteToolRequestApi {
    description: string
    args_schema: WriteToolRequestApiArgsSchema
    source: string
}

/**
 * Body shape for PUT /revisions/<id>/bundle/ — the full-replace typed
 * payload. Skills are not authored here: they come from the llma-skill store
 * via `skill_refs` and are materialized into the bundle at freeze.
 */
export interface WriteTypedBundleRequestApi {
    agent_md: string
    tools?: WriteToolRequestApi[]
    spec: WriteTypedBundleRequestApiSpec
}

/**
 * Body shape for POST /revisions/<id>/clone_from/ — copy every file
 * from `source_revision_id` into this (draft) revision.
 */
export interface CloneFromRequestApi {
    source_revision_id: string
}

export interface AgentRevisionCronFireRequestApi {
    /** `name` of the cron trigger in `spec.triggers[]` to fire. */
    cron_name: string
    /**
     * Stable client-supplied id so repeated clicks of the same UI 'Fire now' button resolve to the same session id rather than firing twice. The janitor keys dedupe off `cron-manual:<rev>:<name>:<request_id>`. Omit to fire unconditionally — every call generates a fresh UUID.
     * @nullable
     */
    request_id?: string | null
}

export interface AgentRevisionCronFireResponseApi {
    ok: boolean
    /** ID of the session the cron firing created (or returned, on dedupe). */
    session_id: string
    /** ISO-8601 timestamp the firing was attributed to. */
    fired_at: string
    /** Composed dedupe key — `cron-manual:<rev>:<name>:<request_id>`. Returned so the UI can correlate. */
    idempotency_key: string
    /** The request id the firing used (echoed back, or freshly minted). */
    request_id: string
}

export interface AgentRevisionEnvKeysResponseApi {
    /** Names of env variables currently set on the revision. Values are never returned. */
    keys: string[]
}

export interface AgentRevisionEnvKeyStatusApi {
    key: string
    /** True if the key is present in the env block. The value itself is never returned. */
    is_set: boolean
}

/**
 * Body shape for AgentApplicationViewSet.env_keys_set — single secret upsert.
 *
 * The view merges `{KEY: value}` into the existing encrypted env block
 * without touching other keys, so callers can set or rotate one secret
 * without needing to read the whole block back.
 */
export interface SetEnvKeyRequestApi {
    value: string
}

export type SetEnvRequestApiEnv = { [key: string]: string }

/**
 * Body shape for AgentApplicationViewSet.set_env.
 *
 * `env` is a JSON object of string→string. The view encrypts it via the
 * same Fernet schedule the worker uses to decrypt.
 */
export interface SetEnvRequestApi {
    env: SetEnvRequestApiEnv
}

/**
 * Body for PUT /revisions/<id>/skill_refs/ — full-replace the draft's references.
 */
export interface SetSkillRefsRequestApi {
    /** The complete set of store-skill references for this draft; replaces any existing references. */
    skill_refs: SkillRefApi[]
}

export interface AgentRevisionSlackManifestResponseApi {
    revision_id: string
    /** Slack app manifest (JSON) ready to paste into https://api.slack.com/apps?new_app=1 → 'From an app manifest'. Scopes and event subscriptions are derived from the agent's slack trigger config + tools. */
    manifest: unknown
    /** Reminders the manifest can't enforce (e.g. invite the bot to its channels). */
    notes: string[]
    /**
     * The Event Subscriptions Request URL baked into the manifest.
     * @nullable
     */
    events_url: string | null
    /**
     * The Interactivity Request URL (used by approval-gated tools).
     * @nullable
     */
    interactivity_url: string | null
}

export type WriteSpecRequestApiSpec = { [key: string]: unknown }

/**
 * Body shape for PUT /revisions/<id>/spec/. The body's `spec` object
 * is the author-facing slice (skills/tools are server-derived at freeze).
 */
export interface WriteSpecRequestApi {
    spec: WriteSpecRequestApiSpec
}

export interface AgentRevisionSystemPromptResponseApi {
    /** UUID of the revision the prompt was rendered for. */
    revision_id: string
    /** Active framework preamble version. Bumps when the platform's `# Platform guidance` content changes meaningfully (decision rules, sections renamed, behavioural defaults flipped). Authors can pin to a specific version via `spec.framework_prompt.version_pin`. */
    framework_prompt_version: number
    /** Fully-assembled system prompt the runner would pass to pi-ai for a session against this revision. Concatenates the platform framework preamble, the bundle's `agent.md`, and the skills index. Inspect before promotion to confirm the model will see what you expect. */
    system_prompt: string
}

export interface AgentRevisionValidationErrorApi {
    code: string
    message: string
    pointer: string
}

export interface AgentRevisionValidateResponseApi {
    ok: boolean
    revision_id: string
    revision_state: string
    errors: AgentRevisionValidationErrorApi[]
    resolved_natives: string[]
}

/**
 * Body shape for POST /revisions/clone_from/ — atomically create a new
 * draft revision under `application_id` and clone its initial bundle from
 * `source_revision_id`. Convenience for the "edit live" flow so the MCP
 * doesn't have to do create-then-clone-from in two calls.
 */
export interface NewDraftRevisionRequestApi {
    application_id: string
    source_revision_id: string
}

/**
 * Resolved creator (id, first_name, email) from `created_by_id`, or null if unset or the user was deleted.
 * @nullable
 */
export type PatchedAgentApplicationApiCreatedBy = {
    readonly id?: number
    readonly first_name?: string
    readonly email?: string
} | null

export interface PatchedAgentApplicationApi {
    readonly id?: string
    readonly team_id?: number
    /** @maxLength 255 */
    name?: string
    /**
     * Globally-unique URL identifier. Server-minted as an opaque random slug on create; only allowlisted first-party teams may set it explicitly. Slugs live in one global namespace (domain-mode ingress routing carries no team).
     * @maxLength 63
     * @pattern ^[-a-zA-Z0-9_]+$
     */
    slug?: string
    description?: string
    /** @nullable */
    readonly live_revision?: string | null
    archived?: boolean
    /** @nullable */
    readonly archived_at?: string | null
    /** @nullable */
    readonly created_by_id?: number | null
    /**
     * Resolved creator (id, first_name, email) from `created_by_id`, or null if unset or the user was deleted.
     * @nullable
     */
    readonly created_by?: PatchedAgentApplicationApiCreatedBy
    readonly created_at?: string
    readonly updated_at?: string
    /**
     * Public URL to paste into the Slack app dashboard under Event Subscriptions → Request URL. Computed from the agent slug and the deployment's ingress routing mode (`AGENT_INGRESS_DOMAIN_SUFFIX` in domain mode, `AGENT_INGRESS_PUBLIC_URL` in path mode). Null when no public agent-ingress URL is configured (e.g. local dev without a tunnel).
     * @nullable
     */
    readonly slack_events_url?: string | null
    /**
     * Public URL to paste into the Slack app dashboard under Interactivity & Shortcuts → Request URL. Same source + null behaviour as `slack_events_url`.
     * @nullable
     */
    readonly slack_interactivity_url?: string | null
    /**
     * Mode-aware base URL the agent's trigger routes hang off — append `/webhook`, `/run`, `/mcp`, etc. Domain mode: `https://<slug><suffix>`; path mode: `<public_url>/agents/<slug>`. Same source + null behaviour as `slack_events_url` (null when no public ingress URL is configured).
     * @nullable
     */
    readonly ingress_base_url?: string | null
}

/**
 * * `queued` - queued
 * * `approving` - approving
 * * `dispatched` - dispatched
 * * `dispatched_failed` - dispatched_failed
 * * `rejected` - rejected
 * * `expired` - expired
 */
export type AgentApprovalRequestStateEnumApi =
    (typeof AgentApprovalRequestStateEnumApi)[keyof typeof AgentApprovalRequestStateEnumApi]

export const AgentApprovalRequestStateEnumApi = {
    Queued: 'queued',
    Approving: 'approving',
    Dispatched: 'dispatched',
    DispatchedFailed: 'dispatched_failed',
    Rejected: 'rejected',
    Expired: 'expired',
} as const

/**
 * Arguments the model proposed. Frozen at intercept time.
 */
export type AgentApprovalRequestApiProposedArgs = { [key: string]: unknown }

/**
 * Approver-edited arguments. Present iff `approval_policy.allow_edit` was true and the approver supplied edits.
 * @nullable
 */
export type AgentApprovalRequestApiDecidedArgs = { [key: string]: unknown } | null

/**
 * Snapshot of the assistant message that emitted the call (text + thinking blocks) — what the approver sees as the model's reasoning.
 */
export type AgentApprovalRequestApiAssistantMessage = { [key: string]: unknown }

/**
 * Resolved approval policy (type: principal|agent, allow_edit) at request time.
 */
export type AgentApprovalRequestApiApproverScope = { [key: string]: unknown }

/**
 * `{result: ...}` on a successful approved dispatch, `{error: "..."}` when the tool threw. Null until the runner has finalised.
 * @nullable
 */
export type AgentApprovalRequestApiDispatchOutcome = { [key: string]: unknown } | null

export interface AgentApprovalRequestApi {
    /** Approval request UUID — stable, used in /approvals/<id>/decide. */
    id: string
    /** UUID of the session that proposed the gated call. */
    session_id: string
    /** UUID of the parent agent application. */
    application_id: string
    /** Team that owns the agent. */
    team_id: number
    /** Revision the gated call was proposed against. */
    revision_id: string
    /** Turn number within the session that emitted the call. */
    turn: number
    /** pi-ai ToolCall.id from the original assistant message; matched into the synthetic tool_result. */
    tool_call_id: string
    /** Tool id the model invoked (e.g. `@posthog/team-delete`). */
    tool_name: string
    /** Arguments the model proposed. Frozen at intercept time. */
    proposed_args: AgentApprovalRequestApiProposedArgs
    /**
     * Approver-edited arguments. Present iff `approval_policy.allow_edit` was true and the approver supplied edits.
     * @nullable
     */
    decided_args: AgentApprovalRequestApiDecidedArgs
    /** Snapshot of the assistant message that emitted the call (text + thinking blocks) — what the approver sees as the model's reasoning. */
    assistant_message: AgentApprovalRequestApiAssistantMessage
    /** Resolved approval policy (type: principal|agent, allow_edit) at request time. */
    approver_scope: AgentApprovalRequestApiApproverScope
    /** Lifecycle state. `queued` = awaiting an approver; `approving` = decision landed and tool dispatch is in flight; `dispatched`/`dispatched_failed` = approved + tool ran; `rejected` = approver said no; `expired` = TTL elapsed.
     *
     * * `queued` - queued
     * * `approving` - approving
     * * `dispatched` - dispatched
     * * `dispatched_failed` - dispatched_failed
     * * `rejected` - rejected
     * * `expired` - expired */
    state: AgentApprovalRequestStateEnumApi
    /**
     * UUID of the user who decided. Null while queued or expired.
     * @nullable
     */
    decision_by: string | null
    /**
     * ISO timestamp of the decision. Null while queued.
     * @nullable
     */
    decision_at: string | null
    /**
     * Free-form reason supplied by the approver. Optional.
     * @nullable
     */
    decision_reason: string | null
    /**
     * `{result: ...}` on a successful approved dispatch, `{error: "..."}` when the tool threw. Null until the runner has finalised.
     * @nullable
     */
    dispatch_outcome: AgentApprovalRequestApiDispatchOutcome
    /** When the model proposed the gated call. */
    created_at: string
    /** When the queued request auto-rejects if no decision arrives. */
    expires_at: string
}

export interface AgentApplicationApprovalsListResponseApi {
    /** Approval requests for this application, newest first. */
    results: AgentApprovalRequestApi[]
}

/**
 * Approver-edited tool arguments. Only honoured when the tool's `approval_policy.allow_edit` is `true`; otherwise the janitor returns 422.
 */
export type DecideApprovalRequestApiEditedArgs = { [key: string]: unknown }

/**
 * * `approve` - approve
 * * `reject` - reject
 */
export type DecisionEnumApi = (typeof DecisionEnumApi)[keyof typeof DecisionEnumApi]

export const DecisionEnumApi = {
    Approve: 'approve',
    Reject: 'reject',
} as const

/**
 * Body shape for POST /agent_applications/<id>/approvals/<approval_id>/decide/.
 */
export interface DecideApprovalRequestApi {
    /** The approver's decision. `approve` runs the tool platform-side with the (possibly edited) args; `reject` records a terminal rejection and wakes the session with a synthetic rejected tool_result.
     *
     * * `approve` - approve
     * * `reject` - reject */
    decision: DecisionEnumApi
    /** Approver-edited tool arguments. Only honoured when the tool's `approval_policy.allow_edit` is `true`; otherwise the janitor returns 422. */
    edited_args?: DecideApprovalRequestApiEditedArgs
    /** Free-form approver note. Surfaces in the session's synthetic tool_result so the model can communicate the reason back to the user. */
    reason?: string
}

export interface AgentApprovalsDecideResponseApi {
    /** Always `true` on a successful decision. */
    ok: boolean
    /** The approval row's new state — `approving` for approve, `rejected` for reject. */
    state: string
}

/**
 * Body forwarded verbatim to the agent ingress for a *preview* invoke of a
 * non-live revision. The meaningful shape depends on the `rest` path segment:
 *
 * - `run` — `{ message }`: the user message that starts a new session.
 * - `send` — `{ session_id, message }`: append a message to a running session.
 * - `cancel` / `listen` — no body.
 *
 * Documents `message` / `session_id` so the generated MCP tool exposes them;
 * any extra keys are still forwarded as-is to ingress.
 */
export interface PreviewProxyInvokeRequestApi {
    /** User message to deliver to the agent. Required for `run` (starts the session) and `send` (appends to it); ignored for `cancel` / `listen`. */
    message?: string
    /** Target session id for `send` — the running session to append the message to. Omit for `run` (a fresh session is created). */
    session_id?: string
}

export interface AgentApplicationPreviewTokenResponseApi {
    /** HS256 JWT bound to (app, rev) with a short TTL. Attach as the `x-agent-preview-token` header (POST/DELETE) or `preview_token` query param (GET, including EventSource) when calling ingress directly. */
    token: string
    /** Token TTL in seconds from issue. Clients should refresh before this elapses. */
    expires_in: number
    /** Slug to use in the ingress URL — `<application_slug>-<revision_uuid_hex>`. Identifies the exact revision, placed in the host (domain mode) or path (path mode) routing prefix. */
    ingress_slug: string
    /** Per-trigger ingress URLs the caller can hit directly, derived from the revision's `spec.triggers[]`. Shape: `{<trigger_type>: {<route_name>: <absolute_url>}}`. Only includes triggers the spec actually declares. Empty when no public agent-ingress URL is configured for the active routing mode. */
    endpoints: unknown
    /** How to attach credentials to those endpoints: preview-token header/query names, the per-trigger accepted auth modes (`trigger_modes`), and a note about the live vs preview-mode gate split. Lets the caller wire auth without grepping the ingress source. */
    auth: unknown
    /** Server-side alternative — `/api/projects/<team>/agent_applications/<slug>/preview-proxy/<path>` mints the JWT for you. Strips caller Authorization, so it works for public-auth agents; agents with required auth need the direct endpoints above. */
    preview_proxy: unknown
}

export interface AgentSessionUsageTotalApi {
    tokens_in: number
    tokens_out: number
    cache_read: number
    cache_write: number
    cost_input: number
    cost_output: number
    cost_cache_read: number
    cost_cache_write: number
    cost_total: number
}

/**
 * * `anonymous` - anonymous
 * * `service` - service
 * * `internal` - internal
 * * `shared_secret` - shared_secret
 * * `slack` - slack
 */
export type AgentSessionPrincipalKindEnumApi =
    (typeof AgentSessionPrincipalKindEnumApi)[keyof typeof AgentSessionPrincipalKindEnumApi]

export const AgentSessionPrincipalKindEnumApi = {
    Anonymous: 'anonymous',
    Service: 'service',
    Internal: 'internal',
    SharedSecret: 'shared_secret',
    Slack: 'slack',
} as const

export interface AgentSessionPrincipalApi {
    /** What kind of principal authenticated the session start.
     *
     * * `anonymous` - anonymous
     * * `service` - service
     * * `internal` - internal
     * * `shared_secret` - shared_secret
     * * `slack` - slack */
    kind: AgentSessionPrincipalKindEnumApi
    /** Stable identifier for the principal (PAT id, slack user id, etc). Absent for anonymous sessions. */
    id?: string
    /** Team the principal belongs to. Absent for anonymous sessions. */
    team_id?: number
}

/**
 * * `queued` - queued
 * * `running` - running
 * * `completed` - completed
 * * `closed` - closed
 * * `cancelled` - cancelled
 * * `failed` - failed
 */
export type AgentSessionStateEnumApi = (typeof AgentSessionStateEnumApi)[keyof typeof AgentSessionStateEnumApi]

export const AgentSessionStateEnumApi = {
    Queued: 'queued',
    Running: 'running',
    Completed: 'completed',
    Closed: 'closed',
    Cancelled: 'cancelled',
    Failed: 'failed',
} as const

/**
 * Trigger-specific metadata stamped at session creation. Discriminated on `kind`: chat | slack | cron | webhook | mcp. The Zod source of truth is `agent-shared/src/runtime/trigger-metadata.ts`; the node side validates and strips unknown keys at the persistence boundary, so consumers can trust `kind` and per-kind fields. TODO: narrow this DictField to a polymorphic serializer mirroring the union (needs `hogli build:openapi`).
 * @nullable
 */
export type AgentSessionSummaryApiTriggerMetadata = { [key: string]: unknown } | null

export interface AgentSessionSummaryApi {
    usage_total: AgentSessionUsageTotalApi
    principal: AgentSessionPrincipalApi | null
    id: string
    application_id: string
    revision_id: string
    state: AgentSessionStateEnumApi
    /** @nullable */
    external_key: string | null
    /**
     * Trigger-specific metadata stamped at session creation. Discriminated on `kind`: chat | slack | cron | webhook | mcp. The Zod source of truth is `agent-shared/src/runtime/trigger-metadata.ts`; the node side validates and strips unknown keys at the persistence boundary, so consumers can trust `kind` and per-kind fields. TODO: narrow this DictField to a polymorphic serializer mirroring the union (needs `hogli build:openapi`).
     * @nullable
     */
    trigger_metadata?: AgentSessionSummaryApiTriggerMetadata
    /** Count of messages in the conversation — the full transcript ships on the detail endpoint. */
    turns: number
    /**
     * Last assistant text (~120 chars). Null for sessions with no assistant turns yet.
     * @nullable
     */
    preview: string | null
    retry_count: number
    created_at: string
    updated_at: string
}

export interface AgentApplicationSessionsListResponseApi {
    results: AgentSessionSummaryApi[]
    /** Total matching sessions before pagination. */
    count: number
}

/**
 * Trigger-specific metadata stamped at session creation. Discriminated on `kind`: chat | slack | cron | webhook | mcp. The Zod source of truth is `agent-shared/src/runtime/trigger-metadata.ts`; the node side validates and strips unknown keys at the persistence boundary, so consumers can trust `kind` and per-kind fields. TODO: narrow this DictField to a polymorphic serializer mirroring the union (needs `hogli build:openapi`).
 * @nullable
 */
export type AgentApplicationSessionsRetrieveResponseApiTriggerMetadata = { [key: string]: unknown } | null

export type AgentConversationUserMessageApiRole =
    (typeof AgentConversationUserMessageApiRole)[keyof typeof AgentConversationUserMessageApiRole]

export const AgentConversationUserMessageApiRole = {
    User: 'user',
} as const

export interface AgentConversationUserMessageApi {
    role: AgentConversationUserMessageApiRole
    /** String shorthand, or array of {type:'text'|'image', ...} parts. */
    content: unknown
    /** Epoch milliseconds. */
    timestamp: number
}

export type AgentConversationAssistantMessageApiRole =
    (typeof AgentConversationAssistantMessageApiRole)[keyof typeof AgentConversationAssistantMessageApiRole]

export const AgentConversationAssistantMessageApiRole = {
    Assistant: 'assistant',
} as const

/**
 * * `stop` - stop
 * * `length` - length
 * * `toolUse` - toolUse
 * * `error` - error
 * * `aborted` - aborted
 */
export type StopReasonEnumApi = (typeof StopReasonEnumApi)[keyof typeof StopReasonEnumApi]

export const StopReasonEnumApi = {
    Stop: 'stop',
    Length: 'length',
    ToolUse: 'toolUse',
    Error: 'error',
    Aborted: 'aborted',
} as const

export type AgentConversationAssistantMessageApiUsage = { [key: string]: unknown }

export interface AgentConversationAssistantMessageApi {
    role: AgentConversationAssistantMessageApiRole
    /** Array of text/thinking/toolCall parts. */
    content: unknown[]
    /** Epoch milliseconds. */
    timestamp: number
    api?: string
    provider?: string
    model?: string
    usage?: AgentConversationAssistantMessageApiUsage
    stopReason?: StopReasonEnumApi
    errorMessage?: string
}

export type AgentConversationToolResultMessageApiRole =
    (typeof AgentConversationToolResultMessageApiRole)[keyof typeof AgentConversationToolResultMessageApiRole]

export const AgentConversationToolResultMessageApiRole = {
    ToolResult: 'toolResult',
} as const

export interface AgentConversationToolResultMessageApi {
    role: AgentConversationToolResultMessageApiRole
    toolCallId: string
    toolName: string
    /** Array of {type:'text'|'image', ...} parts. */
    content: unknown[]
    isError: boolean
    /** Epoch milliseconds. */
    timestamp: number
}

export type AgentConversationMessageApi =
    | AgentConversationUserMessageApi
    | AgentConversationAssistantMessageApi
    | AgentConversationToolResultMessageApi

export interface AgentApplicationSessionsRetrieveResponseApi {
    usage_total: AgentSessionUsageTotalApi
    principal: AgentSessionPrincipalApi | null
    id: string
    application_id: string
    revision_id: string
    team_id: number
    /** @nullable */
    external_key: string | null
    /**
     * Trigger-specific metadata stamped at session creation. Discriminated on `kind`: chat | slack | cron | webhook | mcp. The Zod source of truth is `agent-shared/src/runtime/trigger-metadata.ts`; the node side validates and strips unknown keys at the persistence boundary, so consumers can trust `kind` and per-kind fields. TODO: narrow this DictField to a polymorphic serializer mirroring the union (needs `hogli build:openapi`).
     * @nullable
     */
    trigger_metadata?: AgentApplicationSessionsRetrieveResponseApiTriggerMetadata
    state: AgentSessionStateEnumApi
    /** Full transcript, or the trailing `last_n` messages if `?last_n=` was supplied. */
    conversation: AgentConversationMessageApi[]
    /** Messages that arrived while a turn was in flight; drained into `conversation` at the start of the next turn. */
    pending_inputs: AgentConversationMessageApi[]
    /** Times the janitor has re-queued this session after a stuck-running detection. */
    retry_count: number
    created_at: string
    updated_at: string
    /** True when `?last_n=` was supplied AND the full conversation exceeded it. */
    conversation_trimmed: boolean
    /** Total messages in the untrimmed conversation. Present only when `conversation_trimmed=true`. */
    conversation_total_turns?: number
}

export interface LogEntryApi {
    log_source_id: string
    instance_id: string
    timestamp: string
    level: string
    message: string
}

export interface AgentApplicationSessionLogsResponseApi {
    results: LogEntryApi[]
}

export interface AgentAggregateStatsApi {
    /** Sessions currently in a live state (queued / running). */
    liveCount: number
    /** Sessions created within the `since` window across all states. */
    sessionsInWindowCount: number
    /** Sum of `usage_total.cost_total` across sessions in the window. */
    spendInWindowUsd: number
    /**
     * ISO timestamp of the most recent session update — null when there are no sessions.
     * @nullable
     */
    lastActivityAt: string | null
    /** Sessions in `failed` state created within the window. */
    failedInWindowCount: number
    /** Approval-gated tool requests across the team currently awaiting a decision. 0 on the per-application aggregate (which doesn't roll up approvals). */
    pendingApprovalsCount: number
}

export interface AgentUserConnectionApi {
    id: string
    provider: string
    scopes: string[]
    /** active | revoked */
    state: string
    /** @nullable */
    subject?: string | null
    /** @nullable */
    access_expires_at?: string | null
    created_at: string
    updated_at: string
    /** @nullable */
    revoked_at?: string | null
}

export interface AgentUserWithConnectionsApi {
    id: string
    /** Edge-identity kind: slack | jwt | posthog | service | … */
    principal_kind: string
    principal_id: string
    metadata?: unknown
    created_at: string
    connections: AgentUserConnectionApi[]
}

export interface AgentUsersListApi {
    count: number
    results: AgentUserWithConnectionsApi[]
}

/**
 * Trigger-specific metadata stamped at session creation. Discriminated on `kind`: chat | slack | cron | webhook | mcp. The Zod source of truth is `agent-shared/src/runtime/trigger-metadata.ts`; the node side validates and strips unknown keys at the persistence boundary, so consumers can trust `kind` and per-kind fields. TODO: narrow this DictField to a polymorphic serializer mirroring the union (needs `hogli build:openapi`).
 * @nullable
 */
export type AgentFleetLiveSessionSummaryApiTriggerMetadata = { [key: string]: unknown } | null

export interface AgentFleetLiveSessionSummaryApi {
    usage_total: AgentSessionUsageTotalApi
    principal: AgentSessionPrincipalApi | null
    id: string
    application_id: string
    revision_id: string
    team_id: number
    state: AgentSessionStateEnumApi
    /** @nullable */
    external_key: string | null
    /**
     * Trigger-specific metadata stamped at session creation. Discriminated on `kind`: chat | slack | cron | webhook | mcp. The Zod source of truth is `agent-shared/src/runtime/trigger-metadata.ts`; the node side validates and strips unknown keys at the persistence boundary, so consumers can trust `kind` and per-kind fields. TODO: narrow this DictField to a polymorphic serializer mirroring the union (needs `hogli build:openapi`).
     * @nullable
     */
    trigger_metadata?: AgentFleetLiveSessionSummaryApiTriggerMetadata
    /** Messages in the conversation so far. */
    turns: number
    /**
     * Last assistant text (~120 chars). Null when no assistant turns yet.
     * @nullable
     */
    preview: string | null
    created_at: string
    updated_at: string
}

export interface AgentFleetLiveSessionsResponseApi {
    results: AgentFleetLiveSessionSummaryApi[]
}

export type AgentNativeToolEntryApiSchema = { [key: string]: unknown }

export interface AgentNativeToolEntryApi {
    id: string
    schema: AgentNativeToolEntryApiSchema
}

export interface AgentNativeToolsListResponseApi {
    tools: AgentNativeToolEntryApi[]
}

/**
 * * `user` - user
 */
export type AgentConversationUserMessageRoleEnumApi =
    (typeof AgentConversationUserMessageRoleEnumApi)[keyof typeof AgentConversationUserMessageRoleEnumApi]

export const AgentConversationUserMessageRoleEnumApi = {
    User: 'user',
} as const

/**
 * * `assistant` - assistant
 */
export type AgentConversationAssistantMessageRoleEnumApi =
    (typeof AgentConversationAssistantMessageRoleEnumApi)[keyof typeof AgentConversationAssistantMessageRoleEnumApi]

export const AgentConversationAssistantMessageRoleEnumApi = {
    Assistant: 'assistant',
} as const

/**
 * * `toolResult` - toolResult
 */
export type AgentConversationToolResultMessageRoleEnumApi =
    (typeof AgentConversationToolResultMessageRoleEnumApi)[keyof typeof AgentConversationToolResultMessageRoleEnumApi]

export const AgentConversationToolResultMessageRoleEnumApi = {
    ToolResult: 'toolResult',
} as const

export type AgentApplicationsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type AgentMemoryListFilesParams = {
    /**
     * Optional path prefix to scope the list, e.g. 'incidents/'.
     */
    prefix?: string
}

export type AgentMemoryGetFileParams = {
    /**
     * Memory path returned by the list endpoint, e.g. 'incidents/db.md'.
     */
    path: string
}

export type AgentMemoryUpdateFileParams = {
    /**
     * Memory path to update.
     */
    path: string
}

export type AgentMemoryDeleteFileParams = {
    /**
     * Memory path to delete.
     */
    path: string
}

export type AgentMemorySearchParams = {
    /**
     * Max results (default 10, max 100).
     */
    limit?: number
    /**
     * Optional path prefix to scope the search.
     */
    prefix?: string
    /**
     * Search cue — plain natural language is fine.
     */
    q: string
}

export type AgentMemoryReadTableParams = {
    /**
     * Max rows to return (default 500, max 5000).
     */
    limit?: number
}

export type AgentApplicationsRevisionsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type AgentApplicationsApprovalsListParams = {
    limit?: number
    offset?: number
    /**
     * Filter by approval state. Comma-separated list accepted. Valid values: queued, approving, dispatched, dispatched_failed, rejected, expired. Defaults to all states.
     */
    state?: string
}

export type AgentApplicationsPreviewProxyGetParams = {
    format?: AgentApplicationsPreviewProxyGetFormat
    /**
     * Target draft revision. Must belong to this application and not be live.
     */
    revision_id: string
}

export type AgentApplicationsPreviewProxyGetFormat =
    (typeof AgentApplicationsPreviewProxyGetFormat)[keyof typeof AgentApplicationsPreviewProxyGetFormat]

export const AgentApplicationsPreviewProxyGetFormat = {
    Json: 'json',
    Sse: 'sse',
} as const

export type AgentApplicationsPreviewProxyParams = {
    format?: AgentApplicationsPreviewProxyFormat
    /**
     * Target draft revision. Must belong to this application and not be live.
     */
    revision_id: string
}

export type AgentApplicationsPreviewProxyFormat =
    (typeof AgentApplicationsPreviewProxyFormat)[keyof typeof AgentApplicationsPreviewProxyFormat]

export const AgentApplicationsPreviewProxyFormat = {
    Json: 'json',
    Sse: 'sse',
} as const

export type AgentApplicationsPreviewTokenParams = {
    /**
     * Target draft revision. Must belong to this application and not be live.
     */
    revision_id: string
}

export type AgentApplicationsPreviewTokenMintParams = {
    /**
     * Target draft revision. Must belong to this application and not be live.
     */
    revision_id: string
}

export type AgentApplicationsSessionsListParams = {
    /**
     * ISO datetime — return sessions with created_at >= this.
     */
    created_after?: string
    /**
     * ISO datetime — return sessions with created_at <= this.
     */
    created_before?: string
    limit?: number
    offset?: number
    /**
     * Only return sessions started against this specific revision.
     */
    revision_id?: string
    /**
     * Filter by session state. Comma-separated list accepted (e.g. `completed,failed`). Valid values: queued, running, completed, closed, cancelled, failed.
     */
    state?: string
}

export type AgentApplicationsSessionsRetrieveParams = {
    /**
     * If set, return only the most recent N messages from the conversation. `usage_total` is still computed over the full session — only the transcript is trimmed. The response includes `conversation_trimmed: true` and `conversation_total_turns` so the caller knows how much was hidden.
     */
    last_n?: number
}

export type AgentApplicationsSessionLogsParams = {
    /**
     * Only return entries after this ISO 8601 timestamp.
     */
    after?: string
    /**
     * Only return entries before this ISO 8601 timestamp.
     */
    before?: string
    /**
     * Filter logs to a specific execution instance.
     * @minLength 1
     */
    instance_id?: string
    /**
     * Comma-separated log levels to include, e.g. 'WARN,ERROR'. Valid levels: DEBUG, LOG, INFO, WARN, ERROR.
     * @minLength 1
     */
    level?: string
    /**
     * Maximum number of log entries to return (1-500, default 50).
     * @minimum 1
     * @maximum 500
     */
    limit?: number
    /**
     * Case-insensitive substring search across log messages.
     * @minLength 1
     */
    search?: string
}

export type AgentApplicationsStatsParams = {
    /**
     * ISO datetime — counts spend + session totals from this point forward. Defaults to 24h ago.
     */
    since?: string
}

export type AgentApplicationsSpecSchemaParams = {
    /**
     * Return only this top-level slice of the spec schema to save tokens — one of `models`, `triggers`, `tools`, `mcps`, `skills`, `identity_providers`, `secrets`, `limits`, `reasoning`, `framework_prompt`, `resume`. Omit for the whole spec schema.
     */
    section?: string
}

export type AgentFleetApprovalsListParams = {
    /**
     * Optional agent UUID — narrows the listing to one application.
     */
    agent_id?: string
    limit?: number
    offset?: number
    /**
     * Filter by approval state. Comma-separated list accepted. Valid values: queued, approving, dispatched, dispatched_failed, rejected, expired. Defaults to all states.
     */
    state?: string
}

export type AgentFleetLiveSessionsParams = {
    /**
     * Cap on returned sessions (default 100, max 500).
     */
    limit?: number
}

export type AgentFleetStatsParams = {
    /**
     * ISO datetime — counts spend + session totals from this point forward. Defaults to 24h ago.
     */
    since?: string
}
