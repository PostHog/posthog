// Hand-written client surface for the Loops API
// (`/api/projects/{project_id}/loops/`), mirroring the shape typed-openapi
// emits in `generated.ts` (a `Schemas`-style namespace of response/request
// types plus per-endpoint request functions). Loops routes are not yet in
// the OpenAPI schema this client is generated from, so this module fills the
// gap by hand; once `apps/code/scripts/update-openapi-client.ts` includes
// `/api/projects/{project_id}/loops` and is rerun against a live posthog
// instance, `Schemas.Loop` and friends land in `generated.ts` and this file
// can be deleted in favor of the generated equivalents.
import type { ApiClient, Method } from "./generated";

export namespace LoopSchemas {
  export type LoopVisibilityEnum = "personal" | "team";
  export type LoopOverlapPolicyEnum = "skip" | "allow" | "cancel_previous";
  export type LoopTriggerTypeEnum = "schedule" | "github" | "api";
  export type LoopScheduleSyncStatusEnum = "pending" | "synced" | "failed";
  export type LoopRuntimeAdapterEnum = "claude" | "codex";
  export type LoopReasoningEffortEnum =
    | "low"
    | "medium"
    | "high"
    | "xhigh"
    | "max";
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

  export type LoopGithubTriggerFilters = {
    actions?: Array<string>;
    branches?: Array<string>;
    labels?: Array<string>;
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
     * Replaced wholesale via `replaceLoopSkillBundles`, never through the loop write.
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

export namespace LoopEndpoints {
  export type get_Loops_list = {
    method: "GET";
    path: "/api/projects/{project_id}/loops/";
    requestFormat: "json";
    parameters: {
      query?: Partial<{ limit: number; offset: number }>;
      path: { project_id: string };
    };
    responses: { 200: LoopSchemas.PaginatedLoopList };
  };
  export type post_Loops_create = {
    method: "POST";
    path: "/api/projects/{project_id}/loops/";
    requestFormat: "json";
    parameters: {
      path: { project_id: string };
      body: LoopSchemas.LoopWrite;
    };
    responses: { 201: LoopSchemas.Loop };
  };
  export type get_Loops_retrieve = {
    method: "GET";
    path: "/api/projects/{project_id}/loops/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 200: LoopSchemas.Loop };
  };
  export type patch_Loops_partial_update = {
    method: "PATCH";
    path: "/api/projects/{project_id}/loops/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
      body: LoopSchemas.PatchedLoop;
    };
    responses: { 200: LoopSchemas.Loop };
  };
  export type delete_Loops_destroy = {
    method: "DELETE";
    path: "/api/projects/{project_id}/loops/{id}/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
    };
    responses: { 204: unknown };
  };
  export type post_Loops_run_create = {
    method: "POST";
    path: "/api/projects/{project_id}/loops/{id}/run/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
      header?: { "Idempotency-Key"?: string };
    };
    responses: { 200: LoopSchemas.LoopFireRun };
  };
  export type post_Loops_trigger_create = {
    method: "POST";
    path: "/api/projects/{project_id}/loops/{id}/trigger/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
      header?: { "Idempotency-Key"?: string };
      body: Record<string, unknown>;
    };
    responses: { 200: LoopSchemas.LoopFireRun };
  };
  export type get_Loops_runs_list = {
    method: "GET";
    path: "/api/projects/{project_id}/loops/{id}/runs/";
    requestFormat: "json";
    parameters: {
      query?: Partial<{ cursor: string; limit: number }>;
      path: { id: string; project_id: string };
    };
    responses: { 200: LoopSchemas.LoopRunPage };
  };
  export type post_Loops_preview_create = {
    method: "POST";
    path: "/api/projects/{project_id}/loops/{id}/preview/";
    requestFormat: "json";
    parameters: {
      path: { id: string; project_id: string };
      body?: LoopSchemas.LoopPreviewRequest;
    };
    responses: { 200: LoopSchemas.LoopPreview };
  };
}

const loopsListPath = (projectId: string): string =>
  `/api/projects/${projectId}/loops/`;
const loopDetailPath = (projectId: string, loopId: string): string =>
  `/api/projects/${projectId}/loops/${loopId}/`;
const loopRunPath = (projectId: string, loopId: string): string =>
  `/api/projects/${projectId}/loops/${loopId}/run/`;
const loopTriggerPath = (projectId: string, loopId: string): string =>
  `/api/projects/${projectId}/loops/${loopId}/trigger/`;
const loopRunsPath = (projectId: string, loopId: string): string =>
  `/api/projects/${projectId}/loops/${loopId}/runs/`;
const loopPreviewPath = (projectId: string, loopId: string): string =>
  `/api/projects/${projectId}/loops/${loopId}/preview/`;
const loopSkillBundlesPath = (projectId: string, loopId: string): string =>
  `/api/projects/${projectId}/loops/${loopId}/skill_bundles/`;

function idempotencyHeader(
  idempotencyKey: string | undefined,
): Record<string, string> | undefined {
  return idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined;
}

async function loopsRequest<T>(
  client: ApiClient,
  method: Method,
  path: string,
  options?: {
    query?: Record<string, unknown>;
    body?: unknown;
    header?: Record<string, unknown>;
  },
): Promise<T> {
  const encodeSearchParams =
    client.fetcher.encodeSearchParams ?? client.defaultEncodeSearchParams;
  const parseResponseData =
    client.fetcher.parseResponseData ?? client.defaultParseResponseData;

  const response = await client.fetcher.fetch({
    method,
    path,
    url: new URL(client.baseUrl + path),
    urlSearchParams: encodeSearchParams(options?.query),
    parameters: { body: options?.body, header: options?.header },
  });

  if (!response.ok) {
    throw new LoopsApiError(
      method,
      path,
      response.status,
      await readBody(response),
    );
  }

  return (await parseResponseData(response)) as T;
}

/** Machine-readable body of a rejected loop safety/abuse limit (see the backend's
 * `_loop_limit_response`). `error === "loop_safety_limit"` is the stable marker. */
export interface LoopSafetyLimitBody {
  error: "loop_safety_limit";
  code: string;
  limit: number;
  detail: string;
}

/** Error thrown for any non-2xx loops response, carrying the status and parsed body so
 * callers can distinguish a safety-limit rejection from a generic failure. */
export class LoopsApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(method: string, path: string, status: number, body: unknown) {
    super(
      `Loops API request failed: ${method.toUpperCase()} ${path} [${status}]`,
    );
    this.name = "LoopsApiError";
    this.status = status;
    this.body = body;
  }

  /** The parsed safety-limit body when this is a limit rejection, otherwise null. */
  get safetyLimit(): LoopSafetyLimitBody | null {
    const body = this.body;
    if (
      body != null &&
      typeof body === "object" &&
      (body as { error?: unknown }).error === "loop_safety_limit"
    ) {
      return body as LoopSafetyLimitBody;
    }
    return null;
  }

  /** A human-readable reason extracted from the response body (DRF `detail` or
   * per-field validation errors), or null when the body carries none. */
  get detail(): string | null {
    const body = this.body;
    if (typeof body === "string") return body || null;
    if (body == null || typeof body !== "object" || Array.isArray(body)) {
      return null;
    }
    const record = body as Record<string, unknown>;
    if (typeof record.detail === "string") return record.detail;
    const parts: string[] = [];
    for (const [field, value] of Object.entries(record)) {
      const messages = (Array.isArray(value) ? value : [value]).filter(
        (entry): entry is string => typeof entry === "string",
      );
      if (messages.length > 0) {
        parts.push(`${field}: ${messages.join(" ")}`);
      }
    }
    return parts.length > 0 ? parts.join("\n") : null;
  }
}

async function readBody(response: Response): Promise<unknown> {
  // Only called on the error path, where nothing else consumes the body, so read
  // it directly rather than cloning.
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export async function listLoops(
  client: ApiClient,
  projectId: string,
  query?: LoopEndpoints.get_Loops_list["parameters"]["query"],
): Promise<LoopSchemas.PaginatedLoopList> {
  return loopsRequest(client, "get", loopsListPath(projectId), { query });
}

export async function retrieveLoop(
  client: ApiClient,
  projectId: string,
  loopId: string,
): Promise<LoopSchemas.Loop> {
  return loopsRequest(client, "get", loopDetailPath(projectId, loopId));
}

export async function createLoop(
  client: ApiClient,
  projectId: string,
  body: LoopSchemas.LoopWrite,
): Promise<LoopSchemas.Loop> {
  return loopsRequest(client, "post", loopsListPath(projectId), { body });
}

export async function partialUpdateLoop(
  client: ApiClient,
  projectId: string,
  loopId: string,
  body: LoopSchemas.PatchedLoop,
): Promise<LoopSchemas.Loop> {
  return loopsRequest(client, "patch", loopDetailPath(projectId, loopId), {
    body,
  });
}

export async function destroyLoop(
  client: ApiClient,
  projectId: string,
  loopId: string,
): Promise<void> {
  await loopsRequest(client, "delete", loopDetailPath(projectId, loopId));
}

export async function runLoop(
  client: ApiClient,
  projectId: string,
  loopId: string,
  idempotencyKey?: string,
): Promise<LoopSchemas.LoopFireRun> {
  return loopsRequest(client, "post", loopRunPath(projectId, loopId), {
    header: idempotencyHeader(idempotencyKey),
  });
}

export async function triggerLoop(
  client: ApiClient,
  projectId: string,
  loopId: string,
  payload: Record<string, unknown>,
  idempotencyKey?: string,
): Promise<LoopSchemas.LoopFireRun> {
  return loopsRequest(client, "post", loopTriggerPath(projectId, loopId), {
    body: payload,
    header: idempotencyHeader(idempotencyKey),
  });
}

export async function listLoopRuns(
  client: ApiClient,
  projectId: string,
  loopId: string,
  query?: LoopEndpoints.get_Loops_runs_list["parameters"]["query"],
): Promise<LoopSchemas.LoopRunPage> {
  return loopsRequest(client, "get", loopRunsPath(projectId, loopId), {
    query,
  });
}

export async function replaceLoopSkillBundles(
  client: ApiClient,
  projectId: string,
  loopId: string,
  bundles: Array<LoopSchemas.LoopSkillBundleUpload>,
): Promise<LoopSchemas.Loop> {
  return loopsRequest(client, "put", loopSkillBundlesPath(projectId, loopId), {
    body: { bundles },
  });
}

export async function previewLoop(
  client: ApiClient,
  projectId: string,
  loopId: string,
  body?: LoopSchemas.LoopPreviewRequest,
): Promise<LoopSchemas.LoopPreview> {
  return loopsRequest(client, "post", loopPreviewPath(projectId, loopId), {
    body,
  });
}
