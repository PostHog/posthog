// The loop view model Desktop projects a workflow onto (see
// `packages/ui/src/features/loops/loopHogFlowMapping.ts`). It keeps the shape
// typed-openapi emits in `generated.ts` so the loops screens read one type.
import type { EffortLevel } from "@posthog/shared/domain-types";

export namespace LoopSchemas {
  export type LoopVisibilityEnum = "personal" | "team";
  export type LoopOverlapPolicyEnum = "skip" | "allow" | "cancel_previous";
  export type LoopTriggerTypeEnum = "schedule" | "github" | "api";
  export type LoopScheduleSyncStatusEnum = "pending" | "synced" | "failed";
  export type LoopRuntimeAdapterEnum = "claude" | "codex";
  export type LoopReasoningEffortEnum = EffortLevel;
  export type LoopPosthogMcpScopesEnum = "read_only" | "full";
  export type LoopNotificationEventEnum =
    | "run_completed"
    | "run_failed"
    | "pr_created"
    | "needs_attention";
  export type LoopGithubTriggerEventEnum =
    | "issues"
    | "issue_comment"
    | "pull_request"
    | "push";
  export type LoopFireReasonEnum =
    | "created"
    | "deduped"
    | "overlap_skipped"
    | "rate_capped"
    | "team_rate_capped"
    | "disabled"
    | "gate_blocked"
    | "owner_inactive"
    | "owner_changed";
  export type LoopRunStatusEnum =
    | "not_started"
    | "queued"
    | "in_progress"
    | "completed"
    | "failed"
    | "cancelled";
  export type LoopRunEnvironmentEnum = "local" | "cloud";
  export type LoopSkillSourceEnum = "user" | "repo" | "marketplace" | "codex";

  export type LoopRepositoryEntry = {
    github_integration_id: number;
    full_name: string;
  };

  export type LoopBehaviors = {
    create_prs: boolean;
    watch_ci: boolean;
    fix_review_comments: boolean;
    max_fix_iterations: number;
  };

  export type LoopBehaviorsWrite = Partial<LoopBehaviors>;

  export type LoopConnectors = {
    mcp_installation_ids: Array<string>;
    posthog_mcp_scopes: LoopPosthogMcpScopesEnum;
  };

  export type LoopConnectorsWrite = Partial<LoopConnectors>;

  export type LoopNotificationChannel = {
    enabled: boolean;
    events: Array<LoopNotificationEventEnum>;
    params: Record<string, unknown>;
  };

  export type LoopNotificationChannelWrite = Partial<LoopNotificationChannel>;

  export type LoopNotifications = {
    push: LoopNotificationChannel;
    email: LoopNotificationChannel;
    slack: LoopNotificationChannel;
  };

  export type LoopNotificationsWrite = Partial<{
    push: LoopNotificationChannelWrite;
    email: LoopNotificationChannelWrite;
    slack: LoopNotificationChannelWrite;
  }>;

  /** What a context-attached loop maintains each run. */
  export type LoopContextOutputs = {
    /** File each run into the context's feed as a card. */
    post_to_feed: boolean;
    /** Read and republish the context's context.md each run. */
    update_context: boolean;
    /** Id of a canvas in this context to keep up to date, or null. */
    canvas_id: string | null;
  };

  export type LoopContextOutputsWrite = Partial<LoopContextOutputs>;

  /** The context (a "#channel" / desktop folder) a loop is attached to, plus what it maintains. */
  export type LoopContextTarget = {
    /** Desktop folder id of the attached context. */
    folder_id: string;
    /** Context (channel) name, used to file runs into its feed. */
    name: string;
    outputs: LoopContextOutputs;
  };

  export type LoopContextTargetWrite = {
    folder_id: string;
    name: string;
    outputs?: LoopContextOutputsWrite;
  };

  export type LoopScheduleTriggerConfig = {
    cron_expression?: string;
    timezone?: string;
    run_at?: string;
  };

  /** One condition on the webhook body, for what the named filters below don't
   * cover. `path` is a dot-path of object keys (`requested_team.slug`); the value
   * there must equal one of `equals`. All conditions must match. */
  export type LoopGithubTriggerPayloadFilter = {
    path: string;
    equals: string | Array<string>;
  };

  export type LoopGithubTriggerFilters = {
    actions?: Array<string>;
    branches?: Array<string>;
    labels?: Array<string>;
    payload?: Array<LoopGithubTriggerPayloadFilter>;
  };

  export type LoopGithubTriggerConfig = {
    github_integration_id: number;
    repository: string;
    events: Array<LoopGithubTriggerEventEnum>;
    filters?: LoopGithubTriggerFilters;
  };

  export type LoopApiTriggerConfig = Record<string, never>;

  export type LoopTriggerConfig =
    | LoopScheduleTriggerConfig
    | LoopGithubTriggerConfig
    | LoopApiTriggerConfig;

  export type LoopTrigger = {
    id: string;
    loop_id: string;
    type: LoopTriggerTypeEnum;
    enabled: boolean;
    config: LoopTriggerConfig;
    schedule_sync_status: LoopScheduleSyncStatusEnum | null;
    last_fired_at: string | null;
    created_at: string;
    updated_at: string;
  };

  /** Full desired trigger list is id-stable: entries with a matching `id` are
   * updated in place, entries without one are created, and existing triggers
   * absent from the list on a write are deleted. */
  export type LoopTriggerWrite = {
    id?: string;
    type: LoopTriggerTypeEnum;
    enabled?: boolean;
    config?: LoopTriggerConfig;
  };

  export type Loop = {
    id: string;
    team_id: number;
    created_by_id: number | null;
    name: string;
    description: string;
    visibility: LoopVisibilityEnum;
    instructions: string;
    runtime_adapter: LoopRuntimeAdapterEnum;
    model: string;
    reasoning_effort: LoopReasoningEffortEnum | null;
    repositories: Array<LoopRepositoryEntry>;
    sandbox_environment_id: string | null;
    enabled: boolean;
    /** Why the loop was paused when it wasn't the owner who paused it (e.g.
     * "owner_deactivated", "github_integration_disconnected", "usage_limited",
     * "repeated_failures"), or null for a normal pause. Cleared when the loop is
     * re-enabled. Read-only. */
    disabled_reason: string | null;
    overlap_policy: LoopOverlapPolicyEnum;
    behaviors: LoopBehaviors;
    connectors: LoopConnectors;
    notifications: LoopNotifications;
    /** Context this loop is attached to, or null when unattached. */
    context_target: LoopContextTarget | null;
    /** Backend-set: internal loops are hidden from the UI (never returned by the
     * list/detail API), so this is effectively always false for loops a client can see. */
    internal: boolean;
    /** What created this loop: "user_created" for loops a person made, other values for
     * loops created by a backend flow. Read-only. */
    origin_product: string;
    last_run_at: string | null;
    last_run_status: string | null;
    last_error: string | null;
    consecutive_failures: number;
    created_at: string;
    updated_at: string;
    triggers: Array<LoopTrigger>;
    /** Skill bundles attached to this loop, seeded into every fired run's sandbox.
     * Optional because a backend that predates skill bundles omits the field; treat
     * absence as an empty list. */
    skill_bundles?: Array<LoopSkillBundle>;
  };

  /** A skill bundle attached to a loop. `content_sha256` is the stored snapshot's
   * digest, so a client can detect drift from the local copy of the skill. */
  export type LoopSkillBundle = {
    id: string;
    skill_name: string;
    skill_source: LoopSkillSourceEnum;
    size: number;
    content_sha256: string;
    uploaded_at: string;
  };

  /** One zipped local skill in a skill-bundle replace request. */
  export type LoopSkillBundleUpload = {
    file_name: string;
    skill_name: string;
    skill_source: LoopSkillSourceEnum;
    content_sha256: string;
    bundle_format: "zip";
    content_base64: string;
  };

  /** Request body for create (all required fields present) and partial_update
   * (see `PatchedLoop`) — the backend uses one serializer for both, toggling
   * `partial`. `sandbox_environment` takes an id; the read side returns it as
   * `sandbox_environment_id`. */
  export type LoopWrite = {
    name: string;
    description?: string;
    visibility?: LoopVisibilityEnum;
    instructions: string;
    runtime_adapter: LoopRuntimeAdapterEnum;
    model: string;
    reasoning_effort?: LoopReasoningEffortEnum | null;
    repositories?: Array<LoopRepositoryEntry>;
    sandbox_environment?: string | null;
    enabled?: boolean;
    overlap_policy?: LoopOverlapPolicyEnum;
    behaviors?: LoopBehaviorsWrite;
    connectors?: LoopConnectorsWrite;
    notifications?: LoopNotificationsWrite;
    /** Context to attach this loop to, or null to detach. */
    context_target?: LoopContextTargetWrite | null;
    triggers?: Array<LoopTriggerWrite>;
    /** On a team loop, claim ownership as part of this update so you can edit
     * identity-bearing config (instructions, model, triggers, ...) that only the owner may
     * change. Ignored on personal loops and on create. Write-only. */
    take_ownership?: boolean;
  };

  export type PatchedLoop = Partial<LoopWrite>;

  export type PaginatedLoopList = {
    count: number;
    next: string | null;
    previous: string | null;
    results: Array<Loop>;
    /** Hard cap on non-deleted loops per project. Read this rather than hardcoding a
     * number: the backend is authoritative, so raising it there reflects here on the
     * next list. Creating beyond the cap returns a 429 `loop_safety_limit`. */
    max_loops_per_team: number;
    /** Current non-deleted, user-facing loops in this project, counted against
     * `max_loops_per_team`. At or above the cap, creation is blocked. */
    total_loop_count: number;
  };

  export type LoopRun = {
    id: string;
    task_id: string;
    loop_trigger_id: string | null;
    status: LoopRunStatusEnum;
    environment: LoopRunEnvironmentEnum;
    branch: string | null;
    error_message: string | null;
    output: Record<string, unknown> | null;
    created_at: string;
    completed_at: string | null;
  };

  export type LoopRunPage = {
    results: Array<LoopRun>;
    next_cursor: string | null;
  };

  export type LoopFireRun = {
    created: boolean;
    reason: LoopFireReasonEnum;
    task_id: string | null;
    task_run_id: string | null;
  };

  export type LoopPreviewRequest = {
    trigger_type?: LoopTriggerTypeEnum;
    payload?: unknown;
  };

  export type LoopPreview = {
    instructions: string;
    trigger_type: string;
    trigger_context: string;
  };
}
