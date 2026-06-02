/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface AgentApplicationApi {
    readonly id: string
    readonly team: number
    /** @maxLength 255 */
    name: string
    /** @maxLength 63 */
    slug: string
    description?: string
    /** @nullable */
    readonly live_revision: string | null
    archived?: boolean
    /** @nullable */
    readonly archived_at: string | null
    /** @nullable */
    readonly created_by: number | null
    readonly created_at: string
    readonly updated_at: string
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
 * `ready` - ready
 * `live` - live
 * `archived` - archived
 */
export type AgentRevisionStateEnumApi = (typeof AgentRevisionStateEnumApi)[keyof typeof AgentRevisionStateEnumApi]

export const AgentRevisionStateEnumApi = {
    Draft: 'draft',
    Ready: 'ready',
    Live: 'live',
    Archived: 'archived',
} as const

export type AgentRevisionApiSpecReasoning =
    (typeof AgentRevisionApiSpecReasoning)[keyof typeof AgentRevisionApiSpecReasoning]

export const AgentRevisionApiSpecReasoning = {
    Minimal: 'minimal',
    Low: 'low',
    Medium: 'medium',
    High: 'high',
    Xhigh: 'xhigh',
} as const

export type AgentRevisionApiSpecTriggersItem =
    | {
          type: 'slack'
          config: {
              channel_id?: string
              mention_only: boolean
              trusted_workspaces: string[] | '*'
          }
      }
    | {
          type: 'webhook'
          config: {
              path: string
              secret?: string
          }
      }
    | {
          type: 'cron'
          config: {
              schedule: string
              timezone: string
          }
      }
    | {
          type: 'chat'
          config: {
              require_auth: boolean
          }
      }
    | {
          type: 'mcp'
          config: { [key: string]: unknown }
      }

export type AgentRevisionApiSpecToolsItem =
    | {
          kind: 'native'
          id: string
      }
    | {
          kind: 'custom'
          id: string
          path: string
      }
    | {
          kind: 'custom_template'
          from_template: string
          alias: string
          /** @minimum 0 */
          version?: number
      }
    | {
          kind: 'client'
          /** @minLength 1 */
          id: string
          /** @minLength 1 */
          description: string
          args_schema?: { [key: string]: unknown }
          required?: boolean
          /**
           * @minimum 1
           * @maximum 60000
           */
          timeout_ms?: number
      }

export type AgentRevisionApiSpecMcpsItem =
    | {
          kind: 'agent'
          slug: string
      }
    | {
          kind: 'external'
          url: string
          auth?: {
              integration?: string
          }
          allowlist?: string[]
      }

export type AgentRevisionApiSpecSkillsItem = {
    id: string
    path: string
    description?: string
    from_template?: string
    alias?: string
    /** @minimum 0 */
    version?: number
}

export type AgentRevisionApiSpecLimits = {
    /**
     * @maximum 2147483647
     * @exclusiveMinimum 0
     */
    max_turns: number
    /**
     * @maximum 2147483647
     * @exclusiveMinimum 0
     */
    max_tool_calls: number
    /**
     * @maximum 2147483647
     * @exclusiveMinimum 0
     */
    max_wall_seconds: number
}

export type AgentRevisionApiSpecAuthModesItem =
    | {
          type: 'public'
      }
    | {
          type: 'oauth'
          /** @minLength 1 */
          issuer: string
          scopes?: string[]
      }
    | {
          type: 'pat'
      }
    | {
          type: 'jwt'
          /** @minLength 1 */
          issuer_secret_ref: string
      }
    | {
          type: 'shared_secret'
          /** @minLength 1 */
          header: string
      }
    | {
          type: 'posthog_internal'
      }

export type AgentRevisionApiSpecAuth = {
    modes?: AgentRevisionApiSpecAuthModesItem[]
}

export type AgentRevisionApiSpec = {
    /** @minLength 1 */
    model: string
    triggers: AgentRevisionApiSpecTriggersItem[]
    tools: AgentRevisionApiSpecToolsItem[]
    mcps: AgentRevisionApiSpecMcpsItem[]
    skills: AgentRevisionApiSpecSkillsItem[]
    integrations: string[]
    secrets: string[]
    limits: AgentRevisionApiSpecLimits
    entrypoint: string
    auth: AgentRevisionApiSpecAuth
    reasoning?: AgentRevisionApiSpecReasoning
}

export interface AgentRevisionApi {
    readonly id: string
    readonly application: string
    /** @nullable */
    parent_revision?: string | null
    readonly state: AgentRevisionStateEnumApi
    bundle_uri?: string
    /** @nullable */
    readonly bundle_sha256: string | null
    spec?: AgentRevisionApiSpec
    /** @nullable */
    readonly created_by: number | null
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

export type PatchedAgentRevisionApiSpecTriggersItem =
    | {
          type: 'slack'
          config: {
              channel_id?: string
              mention_only: boolean
              trusted_workspaces: string[] | '*'
          }
      }
    | {
          type: 'webhook'
          config: {
              path: string
              secret?: string
          }
      }
    | {
          type: 'cron'
          config: {
              schedule: string
              timezone: string
          }
      }
    | {
          type: 'chat'
          config: {
              require_auth: boolean
          }
      }
    | {
          type: 'mcp'
          config: { [key: string]: unknown }
      }

export type PatchedAgentRevisionApiSpecToolsItem =
    | {
          kind: 'native'
          id: string
      }
    | {
          kind: 'custom'
          id: string
          path: string
      }
    | {
          kind: 'custom_template'
          from_template: string
          alias: string
          /** @minimum 0 */
          version?: number
      }
    | {
          kind: 'client'
          /** @minLength 1 */
          id: string
          /** @minLength 1 */
          description: string
          args_schema?: { [key: string]: unknown }
          required?: boolean
          /**
           * @minimum 1
           * @maximum 60000
           */
          timeout_ms?: number
      }

export type PatchedAgentRevisionApiSpecMcpsItem =
    | {
          kind: 'agent'
          slug: string
      }
    | {
          kind: 'external'
          url: string
          auth?: {
              integration?: string
          }
          allowlist?: string[]
      }

export type PatchedAgentRevisionApiSpecSkillsItem = {
    id: string
    path: string
    description?: string
    from_template?: string
    alias?: string
    /** @minimum 0 */
    version?: number
}

export type PatchedAgentRevisionApiSpecLimits = {
    /**
     * @maximum 2147483647
     * @exclusiveMinimum 0
     */
    max_turns: number
    /**
     * @maximum 2147483647
     * @exclusiveMinimum 0
     */
    max_tool_calls: number
    /**
     * @maximum 2147483647
     * @exclusiveMinimum 0
     */
    max_wall_seconds: number
}

export type PatchedAgentRevisionApiSpecAuthModesItem =
    | {
          type: 'public'
      }
    | {
          type: 'oauth'
          /** @minLength 1 */
          issuer: string
          scopes?: string[]
      }
    | {
          type: 'pat'
      }
    | {
          type: 'jwt'
          /** @minLength 1 */
          issuer_secret_ref: string
      }
    | {
          type: 'shared_secret'
          /** @minLength 1 */
          header: string
      }
    | {
          type: 'posthog_internal'
      }

export type PatchedAgentRevisionApiSpecAuth = {
    modes?: PatchedAgentRevisionApiSpecAuthModesItem[]
}

export type PatchedAgentRevisionApiSpecReasoning =
    (typeof PatchedAgentRevisionApiSpecReasoning)[keyof typeof PatchedAgentRevisionApiSpecReasoning]

export const PatchedAgentRevisionApiSpecReasoning = {
    Minimal: 'minimal',
    Low: 'low',
    Medium: 'medium',
    High: 'high',
    Xhigh: 'xhigh',
} as const

export type PatchedAgentRevisionApiSpec = {
    /** @minLength 1 */
    model: string
    triggers: PatchedAgentRevisionApiSpecTriggersItem[]
    tools: PatchedAgentRevisionApiSpecToolsItem[]
    mcps: PatchedAgentRevisionApiSpecMcpsItem[]
    skills: PatchedAgentRevisionApiSpecSkillsItem[]
    integrations: string[]
    secrets: string[]
    limits: PatchedAgentRevisionApiSpecLimits
    entrypoint: string
    auth: PatchedAgentRevisionApiSpecAuth
    reasoning?: PatchedAgentRevisionApiSpecReasoning
}

export interface PatchedAgentRevisionApi {
    readonly id?: string
    readonly application?: string
    /** @nullable */
    parent_revision?: string | null
    readonly state?: AgentRevisionStateEnumApi
    bundle_uri?: string
    /** @nullable */
    readonly bundle_sha256?: string | null
    spec?: PatchedAgentRevisionApiSpec
    /** @nullable */
    readonly created_by?: number | null
    readonly created_at?: string
    readonly updated_at?: string
}

export type WriteBundleRequestApiFiles = { [key: string]: string }

/**
 * * `replace` - replace
 * `merge` - merge
 */
export type WriteBundleRequestModeEnumApi =
    (typeof WriteBundleRequestModeEnumApi)[keyof typeof WriteBundleRequestModeEnumApi]

export const WriteBundleRequestModeEnumApi = {
    Replace: 'replace',
    Merge: 'merge',
} as const

/**
 * Body shape for PUT /revisions/<id>/bundle/ — the bulk upload.

`files` is a `{path: utf-8 content}` map. `mode='replace'` wipes the
existing bundle before writing the new set; `'merge'` upserts.
 */
export interface WriteBundleRequestApi {
    files: WriteBundleRequestApiFiles
    mode?: WriteBundleRequestModeEnumApi
}

/**
 * Body shape for POST /revisions/<id>/clone_from/ — copy every file
from `source_revision_id` into this (draft) revision.
 */
export interface CloneFromRequestApi {
    source_revision_id: string
}

/**
 * Body shape for PUT /revisions/<id>/file/. `path` lives in the query
string (matches the janitor wire format); `content` is the new file body.
 */
export interface WriteFileRequestApi {
    content: string
}

export interface AgentRevisionSystemPromptResponseApi {
    /** UUID of the revision the prompt was rendered for. */
    revision_id: string
    /** Active framework preamble version. Bumps when the platform's `# Platform guidance` content changes meaningfully (decision rules, sections renamed, behavioural defaults flipped). Authors can pin to a specific version via `spec.framework_prompt.version_pin`. */
    framework_prompt_version: number
    /** Fully-assembled system prompt the runner would pass to pi-ai for a session against this revision. Concatenates the platform framework preamble, the bundle's `agent.md` (or `spec.entrypoint`), and the skills index. Inspect before promotion to confirm the model will see what you expect — see docs/agent-platform/plans/framework-system-prompt.md §4. */
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
draft revision under `application_id` and clone its initial bundle from
`source_revision_id`. Convenience for the "edit live" flow so the MCP
doesn't have to do create-then-clone-from in two calls.
 */
export interface NewDraftRevisionRequestApi {
    application_id: string
    source_revision_id: string
}

export interface PatchedAgentApplicationApi {
    readonly id?: string
    readonly team?: number
    /** @maxLength 255 */
    name?: string
    /** @maxLength 63 */
    slug?: string
    description?: string
    /** @nullable */
    readonly live_revision?: string | null
    archived?: boolean
    /** @nullable */
    readonly archived_at?: string | null
    /** @nullable */
    readonly created_by?: number | null
    readonly created_at?: string
    readonly updated_at?: string
}

/**
 * * `queued` - queued
 * `approving` - approving
 * `dispatched` - dispatched
 * `dispatched_failed` - dispatched_failed
 * `rejected` - rejected
 * `expired` - expired
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
 * Resolved approver policy (approvers, allow_edit, allow_agent_approver) at request time.
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
    /** Resolved approver policy (approvers, allow_edit, allow_agent_approver) at request time. */
    approver_scope: AgentApprovalRequestApiApproverScope
    /** Lifecycle state. `queued` = awaiting an approver; `approving` = decision landed and tool dispatch is in flight; `dispatched`/`dispatched_failed` = approved + tool ran; `rejected` = approver said no; `expired` = TTL elapsed.

  * `queued` - queued
  * `approving` - approving
  * `dispatched` - dispatched
  * `dispatched_failed` - dispatched_failed
  * `rejected` - rejected
  * `expired` - expired */
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
 * `reject` - reject
 */
export type DecisionEnumApi = (typeof DecisionEnumApi)[keyof typeof DecisionEnumApi]

export const DecisionEnumApi = {
    Approve: 'approve',
    Reject: 'reject',
} as const

/**
 * Body shape for POST /agent_applications/<id>/approvals/<approval_id>/decide/.

See docs/agent-platform/plans/approval-gated-tools.md.
 */
export interface DecideApprovalRequestApi {
    /** The approver's decision. `approve` runs the tool platform-side with the (possibly edited) args; `reject` records a terminal rejection and wakes the session with a synthetic rejected tool_result.

  * `approve` - approve
  * `reject` - reject */
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

export interface AgentApplicationEnvKeysResponseApi {
    /** Names of env variables currently set on the application. Values are never returned. */
    keys: string[]
}

export interface AgentApplicationEnvKeyStatusApi {
    key: string
    /** True if the key is present in the env block. The value itself is never returned. */
    is_set: boolean
}

/**
 * Body shape for AgentApplicationViewSet.env_keys_set — single secret upsert.

The view merges `{KEY: value}` into the existing encrypted env block
without touching other keys, so callers can set or rotate one secret
without needing to read the whole block back.
 */
export interface SetEnvKeyRequestApi {
    value: string
}

export interface AgentApplicationPreviewTokenResponseApi {
    /** HS256 JWT bound to (app, rev) with a short TTL. Attach as the `x-agent-preview-token` header (POST/DELETE) or `preview_token` query param (GET, including EventSource) when calling ingress directly. */
    token: string
    /** Token TTL in seconds from issue. Clients should refresh before this elapses. */
    expires_in: number
    /** Slug to use in the ingress URL — `<application_slug>-<revision_uuid_hex>`. Identifies the exact revision in the path-routing prefix. */
    ingress_slug: string
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
 * `service` - service
 * `internal` - internal
 * `shared_secret` - shared_secret
 * `slack` - slack
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

  * `anonymous` - anonymous
  * `service` - service
  * `internal` - internal
  * `shared_secret` - shared_secret
  * `slack` - slack */
    kind: AgentSessionPrincipalKindEnumApi
    /** Stable identifier for the principal (PAT id, slack user id, etc). Absent for anonymous sessions. */
    id?: string
    /** Team the principal belongs to. Absent for anonymous sessions. */
    team_id?: number
}

/**
 * * `queued` - queued
 * `running` - running
 * `completed` - completed
 * `closed` - closed
 * `cancelled` - cancelled
 * `failed` - failed
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

export interface AgentSessionSummaryApi {
    usage_total: AgentSessionUsageTotalApi
    principal: AgentSessionPrincipalApi | null
    id: string
    application_id: string
    revision_id: string
    state: AgentSessionStateEnumApi
    /** @nullable */
    external_key: string | null
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
 * `length` - length
 * `toolUse` - toolUse
 * `error` - error
 * `aborted` - aborted
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

export type SetEnvRequestApiEnv = { [key: string]: string }

/**
 * Body shape for AgentApplicationViewSet.set_env.

`env` is a JSON object of string→string. The view encrypts it via the
same Fernet schedule the worker uses to decrypt.
 */
export interface SetEnvRequestApi {
    env: SetEnvRequestApiEnv
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
}

/**
 * * `engineering` - Engineering
 * `data` - Data
 * `product` - Product Management
 * `founder` - Founder
 * `leadership` - Leadership
 * `marketing` - Marketing
 * `sales` - Sales / Success
 * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

export interface CustomToolTemplateSummaryApi {
    readonly id: string
    readonly name: string
    readonly description: string
    readonly version: number
    readonly is_latest: boolean
    readonly requires_secrets: readonly string[]
    /** Number of frozen agent revisions pinning this template (any version). */
    readonly usage_count: number
    /** Publisher. Null for canonical PostHog-owned templates. */
    readonly created_by: UserBasicApi
    readonly updated_at: string
}

export interface CustomToolTemplateCreateApi {
    /**
     * Slug-shaped name unique per team.
     * @maxLength 128
     */
    name: string
    /**
     * One-line description.
     * @maxLength 4096
     */
    description?: string
    /** TypeScript source. */
    source?: string
    /** Bundler output. The publisher (UI or MCP) computes this client-side. */
    compiled_js?: string
    /** TypeBox / JSON Schema for tool args. */
    args_schema?: unknown
    /** Optional TypeBox / JSON Schema for the return value. */
    returns_schema?: unknown
    /** Names of secrets the tool reads via `ctx.secret(...)`. */
    requires_secrets?: string[]
}

export interface CustomToolTemplateDetailApi {
    readonly id: string
    readonly name: string
    readonly description: string
    readonly version: number
    readonly is_latest: boolean
    readonly requires_secrets: readonly string[]
    /** Number of frozen agent revisions pinning this template (any version). */
    readonly usage_count: number
    /** Publisher. Null for canonical PostHog-owned templates. */
    readonly created_by: UserBasicApi
    readonly updated_at: string
    /** TypeScript source the bundler compiles to `compiled_js`. */
    source: string
    /** Last bundle output. Copied into `bundle/tools/<alias>/compiled.js` at freeze. */
    compiled_js: string
    /** TypeBox / JSON Schema for tool args. */
    args_schema: unknown
    /** Optional TypeBox / JSON Schema for the return value (informational). */
    returns_schema?: unknown
}

export interface CustomToolTemplateDuplicateApi {
    /**
     * Slug for the duplicate.
     * @maxLength 128
     */
    name: string
    /**
     * Description for the new template.
     * @maxLength 4096
     */
    description?: string
}

/**
 * Structured edit applied to source.
 */
export interface CustomToolTemplateEditApi {
    /** Text to locate (must match exactly once). */
    old: string
    /** Replacement text. */
    new: string
}

export interface CustomToolTemplatePublishApi {
    /**
     * Overrides the prior description. Omit to keep the prior value.
     * @maxLength 4096
     */
    description?: string
    /** Full new TypeScript source. Mutually exclusive with `edits`. */
    source?: string
    /** Structured edits against the current source. */
    edits?: CustomToolTemplateEditApi[]
    /** Updated bundle output. Required when `source` or `edits` are supplied. */
    compiled_js?: string
    /** Overrides args_schema. Omit to keep prior value. */
    args_schema?: unknown
    /** Overrides returns_schema. Omit to keep prior value. */
    returns_schema?: unknown
    /** Overrides requires_secrets. Omit to keep prior value. */
    requires_secrets?: string[]
}

export interface CustomToolTemplateUsageApi {
    /** Slug of the agent whose revision pins this tool. */
    agent_slug: string
    /** Display name of the agent. */
    agent_name: string
    /** Frozen revision id. */
    revision_id: string
    /** First 8 chars of the revision id, for display. */
    revision_short_id: string
    /** Tool version pinned at freeze. */
    pinned_version: number
}

/**
 * Read shape used by `…/versions/` on both template families.
 */
export interface TemplateVersionEntryApi {
    /** Version number. */
    version: number
    /** True for the current row in this version's name lineage. */
    is_latest: boolean
    /** Publisher. Null for canonical. */
    created_by: UserBasicApi | null
    /** When this version was published. */
    updated_at: string
}

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
 * List shape — no body / file contents (keeps the index page fast).
 */
export interface SkillTemplateSummaryApi {
    readonly id: string
    readonly name: string
    readonly description: string
    readonly version: number
    readonly is_latest: boolean
    /** Number of companion files attached to the current version. */
    readonly file_count: number
    /** Number of frozen agent revisions pinning this template (any version). */
    readonly usage_count: number
    /** Agent Skills `license` frontmatter — license name or a reference to a bundled license file. Blank if unset. */
    license: string
    /** Agent Skills `compatibility` frontmatter — environment requirements (intended product, packages, network). Blank if unset. */
    compatibility: string
    readonly metadata: unknown
    readonly allowed_tools: unknown
    /** Publisher. Null for canonical PostHog-owned templates. */
    readonly created_by: UserBasicApi
    readonly updated_at: string
}

export interface SkillTemplateFileApi {
    readonly id: string
    /**
     * Relative path inside the skill folder; may include subfolders (e.g. `references/api.md`, `scripts/run.py`, `assets/x/y.json`). Becomes `bundle/skills/<alias>/<path>` at freeze. No `..` traversal or absolute paths.
     * @maxLength 512
     */
    path: string
    /** File body. Plain text or markdown — companion files are not interpreted by the runner. */
    content: string
    /**
     * MIME type hint. Read-only at runtime; aids the registry UI's file viewer.
     * @maxLength 128
     */
    content_type?: string
}

/**
 * Initial-create payload — produces v1.
 */
export interface SkillTemplateCreateApi {
    /**
     * Slug-shaped name unique per team (max 64 chars, per the Agent Skills spec). `@posthog/<slug>` is reserved for canonical templates.
     * @maxLength 64
     */
    name: string
    /**
     * Required description (1–1024 chars, per the Agent Skills spec) — what the skill does and when to use it. Shown in the list view + system-prompt skill index.
     * @maxLength 1024
     */
    description: string
    /** Initial SKILL.md markdown body. Any leading YAML frontmatter is stripped at freeze — frontmatter is assembled from the structured fields. */
    body?: string
    /**
     * Agent Skills `license` frontmatter — license name or a reference to a bundled license file.
     * @maxLength 256
     */
    license?: string
    /**
     * Agent Skills `compatibility` frontmatter — environment requirements (intended product, packages, network access). Max 500 chars.
     * @maxLength 500
     */
    compatibility?: string
    /** Optional companion files (scripts/, references/, assets/ — arbitrarily nested) at creation time. */
    files?: SkillTemplateFileApi[]
    /** Agent Skills `metadata` map (string → string) for non-promoted keys like author or version. */
    metadata?: unknown
    /** Optional list of tool ids the skill expects to reach for. Emitted as the spec's space-separated `allowed-tools` frontmatter at freeze. */
    allowed_tools?: unknown
}

/**
 * Detail shape: adds body + files. Used by the registry detail page.
 */
export interface SkillTemplateDetailApi {
    readonly id: string
    readonly name: string
    readonly description: string
    readonly version: number
    readonly is_latest: boolean
    /** Number of companion files attached to the current version. */
    readonly file_count: number
    /** Number of frozen agent revisions pinning this template (any version). */
    readonly usage_count: number
    /** Agent Skills `license` frontmatter — license name or a reference to a bundled license file. Blank if unset. */
    license: string
    /** Agent Skills `compatibility` frontmatter — environment requirements (intended product, packages, network). Blank if unset. */
    compatibility: string
    readonly metadata: unknown
    readonly allowed_tools: unknown
    /** Publisher. Null for canonical PostHog-owned templates. */
    readonly created_by: UserBasicApi
    readonly updated_at: string
    /** Markdown body. The `SKILL.md` equivalent. */
    body: string
    /** Companion files attached to this version. */
    readonly files: readonly SkillTemplateFileApi[]
}

export interface SkillTemplateDuplicateApi {
    /**
     * Slug for the new duplicate (max 64 chars). Must not collide with an existing template.
     * @maxLength 64
     */
    name: string
    /**
     * Description for the new template (1–1024 chars, non-empty). Omit to keep the source's description.
     * @maxLength 1024
     */
    description?: string
}

export interface SkillTemplateFileWriteApi {
    /**
     * Relative path inside the skill folder; may include subfolders (e.g. `references/api.md`, `scripts/run.py`). No `..` traversal or absolute paths.
     * @maxLength 512
     */
    path: string
    /** File body. */
    content: string
    /**
     * MIME type hint.
     * @maxLength 128
     */
    content_type?: string
}

export interface SkillTemplateFileRenameApi {
    /**
     * Existing file path inside the skill folder (subfolders allowed).
     * @maxLength 512
     */
    from_path: string
    /**
     * New path (subfolders allowed); may move the file between subfolders. Must not collide with another file.
     * @maxLength 512
     */
    to_path: string
}

/**
 * A single find/replace edit applied to body or a file's content.
 */
export interface SkillTemplateEditApi {
    /** Text to locate (must match exactly once). */
    old: string
    /** Replacement text. */
    new: string
    /**
     * Apply this edit to a companion file instead of the body. Null/omitted = body edit.
     * @nullable
     */
    file_path?: string | null
}

/**
 * Publish a new version.

Supply EITHER `body` (full overwrite) OR `edits` (structured
find/replace). The viewset rejects requests carrying both.
 */
export interface SkillTemplatePublishApi {
    /**
     * Overrides the prior description (1–1024 chars, non-empty). Omit to keep the prior value.
     * @maxLength 1024
     */
    description?: string
    /** Full new body. Mutually exclusive with `edits`. */
    body?: string
    /** Structured edits. Each `old` must match exactly once in the current body / file. */
    edits?: SkillTemplateEditApi[]
    /**
     * Overrides the `license` frontmatter. Omit to keep the prior value.
     * @maxLength 256
     */
    license?: string
    /**
     * Overrides the `compatibility` frontmatter (max 500 chars). Omit to keep the prior value.
     * @maxLength 500
     */
    compatibility?: string
    /** Overrides the metadata map. Omit to keep the prior value. */
    metadata?: unknown
    /** Overrides allowed_tools. Omit to keep the prior value. */
    allowed_tools?: unknown
}

/**
 * Read shape returned by `…/usages/`. Sourced from the join table.
 */
export interface SkillTemplateUsageApi {
    /** Slug of the agent whose revision pins this template. */
    agent_slug: string
    /** Display name of the agent. */
    agent_name: string
    /** Frozen revision id. */
    revision_id: string
    /** First 8 chars of the revision id, for display. */
    revision_short_id: string
    /** Template version pinned at freeze. */
    pinned_version: number
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

export type AgentApplicationsRevisionsFileRetrieveParams = {
    /**
     * Bundle-relative file path, e.g. `agent.md` or `skills/research.md`.
     */
    path: string
}

export type AgentApplicationsRevisionsFileUpdateParams = {
    /**
     * Bundle-relative file path, e.g. `agent.md` or `skills/research.md`.
     */
    path: string
}

export type AgentApplicationsRevisionsFileDestroyParams = {
    /**
     * Bundle-relative file path, e.g. `agent.md` or `skills/research.md`.
     */
    path: string
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

export type AgentCustomToolTemplatesListParams = {
    /**
     * Optional substring filter against name + description.
     */
    search?: string
}

export type AgentCustomToolTemplatesNameRetrieveParams = {
    /**
     * Fetch a specific version.
     */
    version?: number
}

export type AgentCustomToolTemplatesNameUsagesListParams = {
    /**
     * Filter to a specific pinned version.
     */
    pinned_version?: number
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

export type AgentSkillTemplatesListParams = {
    /**
     * Optional substring filter against name + description.
     */
    search?: string
}

export type AgentSkillTemplatesNameRetrieveParams = {
    /**
     * Fetch a specific version. Omit for the current `is_latest=true` row.
     */
    version?: number
}

export type AgentSkillTemplatesNameUsagesListParams = {
    /**
     * Filter to revisions stuck on a specific version (`/?pinned_version=3`).
     */
    pinned_version?: number
}
