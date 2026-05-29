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

export type AgentRevisionApiSpecAuthMode =
    (typeof AgentRevisionApiSpecAuthMode)[keyof typeof AgentRevisionApiSpecAuthMode]

export const AgentRevisionApiSpecAuthMode = {
    Public: 'public',
    Pat: 'pat',
    PosthogInternal: 'posthog_internal',
    SharedSecret: 'shared_secret',
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

export type AgentRevisionApiSpecAuth = {
    mode: AgentRevisionApiSpecAuthMode
    header?: string
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

export type PatchedAgentRevisionApiSpecAuthMode =
    (typeof PatchedAgentRevisionApiSpecAuthMode)[keyof typeof PatchedAgentRevisionApiSpecAuthMode]

export const PatchedAgentRevisionApiSpecAuthMode = {
    Public: 'public',
    Pat: 'pat',
    PosthogInternal: 'posthog_internal',
    SharedSecret: 'shared_secret',
} as const

export type PatchedAgentRevisionApiSpecAuth = {
    mode: PatchedAgentRevisionApiSpecAuthMode
    header?: string
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
 * @nullable
 */
export type AgentSessionSummaryApiPrincipal = { [key: string]: unknown } | null

export interface AgentSessionSummaryApi {
    id: string
    application_id: string
    revision_id: string
    state: string
    /** @nullable */
    external_key: string | null
    /** @nullable */
    principal: AgentSessionSummaryApiPrincipal
    turns: number
    /** @nullable */
    preview: string | null
    usage_total: AgentSessionUsageTotalApi
    retry_count: number
    created_at: string
    updated_at: string
}

export interface AgentApplicationSessionsListResponseApi {
    sessions: AgentSessionSummaryApi[]
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

export type AgentNativeToolEntryApiSchema = { [key: string]: unknown }

export interface AgentNativeToolEntryApi {
    id: string
    schema: AgentNativeToolEntryApiSchema
}

export interface AgentNativeToolsListResponseApi {
    tools: AgentNativeToolEntryApi[]
}

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
    /**
     * Target draft revision. Must belong to this application and not be live.
     */
    revision_id: string
}

export type AgentApplicationsPreviewProxyParams = {
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
     * Filter by session state. Comma-separated list accepted (e.g. `completed,failed`). Valid values: queued, running, waiting, completed, failed.
     */
    state?: string
}

export type AgentApplicationsSessionsRetrieveParams = {
    /**
     * If set, return only the most recent N messages from the conversation. `usage_total` is still computed over the full session — only the transcript is trimmed. The response includes `conversation_trimmed: true` and `conversation_total_turns` so the caller knows how much was hidden.
     */
    last_n?: number
}
