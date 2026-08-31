// Hand-written client surface for the subset of the Workflows API
// (`/api/projects/{project_id}/hog_flows/`) that the Desktop "loops" feature
// needs to run schedule-triggered agent automations on the HogFlow engine
// instead of the bespoke Loops API (`./loops.ts`). Mirrors that file's
// pattern: a `Schemas`-style namespace plus per-endpoint request functions,
// built on the shared `ApiClient`/`Fetcher` plumbing rather than the
// typed-openapi `generated.ts` client.
//
// `generated.ts` does carry some hog_flows types already, but its shapes are
// unreliable for this feature (e.g. the schedules-create endpoint is typed
// with a `HogFlow` request body instead of the schedule fields it actually
// takes), and it has no entry at all for the `run` action or the "Create AI
// task" action's `skills` input — both still on open PRs (run action + task
// filter: #91581; team-skill input: #91699). This module hand-vendors those
// pieces the same way `loops.ts` hand-vendors routes ahead of OpenAPI
// generation; once both PRs merge and the client regenerates, the vendored
// parts can be replaced with the generated equivalents.
import type { ApiClient, Method } from "./generated";

export const CREATE_TASK_TEMPLATE_ID = "template-posthog-create-task";

/** Canonical action ids this feature writes. A HogFlow's `actions` array is id-addressed, not
 * positional, so a fixed id per role keeps writes and shape-detection simple. */
export const TRIGGER_ACTION_ID = "trigger_node";
export const CREATE_TASK_ACTION_ID = "create_ai_task";

/** The engine treats a 4xx as a step failure before the action's own code runs, unless the
 * status is listed here. 409 ("task limit reached") is a graceful skip, pinned explicitly per
 * the editor node convention (see `AI_TASK_ACTION_NODE` in the Workflows product) rather than
 * left to the template's default. */
export const CREATE_TASK_NON_FAILURE_STATUS_CODES = [409];

export namespace WorkflowSchemas {
  export type HogFlowStatus = "draft" | "active" | "archived";

  /** The only trigger shape this feature writes. A HogFlow with any other `trigger.type`
   * (event, batch, webhook, ...) is out of scope — see `isLoopShapedHogFlow`. */
  export type ScheduleTrigger = { type: "schedule" };

  export type HogFlowTrigger = ScheduleTrigger | { type: string };

  export type CreateTaskModelInput = {
    model: string;
    reasoning_effort?: string | null;
  };

  export type CreateTaskActionInputs = {
    prompt: { value: string };
    title?: { value: string };
    model?: { value: CreateTaskModelInput };
    repository?: { value: string };
    connectors?: { value: string[] };
    /** Team skill names from the skills store (see products/skills). Hand-vendored ahead of
     * #91699 landing. */
    skills?: { value: string[] };
    posthog_mcp_scopes?: { value: "read_only" | "full" };
    max_parallel_tasks?: { value: number };
    non_failure_status_codes: { value: number[] };
  };

  /** The HogFlow's own trigger node — every flow's `actions` array carries one, mirrored onto
   * the top-level (read-only) `trigger` field by the backend. */
  export type TriggerAction = {
    id: string;
    name: string;
    type: "trigger";
    config: HogFlowTrigger;
  };

  /** The "Create AI task" function action, matching the `AI_TASK_ACTION_NODE` shape the
   * Workflows editor writes. */
  export type CreateTaskAction = {
    id: string;
    name: string;
    description?: string;
    type: "function";
    config: {
      template_id: typeof CREATE_TASK_TEMPLATE_ID;
      inputs: CreateTaskActionInputs;
    };
    output_variable?: {
      key: string;
      result_path: string | null;
      label: string;
    } | null;
  };

  /** Any other action type this feature doesn't author but must round-trip untouched (e.g. a
   * flow hand-edited in the main-app workflow editor). */
  export type OtherAction = {
    id: string;
    name: string;
    type: string;
    config: unknown;
  };

  export type HogFlowAction = TriggerAction | CreateTaskAction | OtherAction;

  export type HogFlowEdge = {
    from: string;
    to: string;
    type?: string;
  };

  export type UserBasic = {
    id: number;
    email: string;
    first_name?: string;
    last_name?: string;
  };

  export type HogFlow = {
    id: string;
    name: string | null;
    description: string;
    version: number;
    status: HogFlowStatus;
    created_at: string;
    created_by: UserBasic;
    updated_at: string;
    trigger: HogFlowTrigger;
    edges: HogFlowEdge[];
    actions: HogFlowAction[];
    abort_action: string | null;
    variables: Array<Record<string, string>> | null;
    schedules: HogFlowSchedule[];
    user_access_level: string | null;
  };

  export type HogFlowMinimal = {
    id: string;
    name: string | null;
    description: string;
    version: number;
    status: HogFlowStatus;
    created_at: string;
    created_by: UserBasic;
    updated_at: string;
    trigger: HogFlowTrigger;
    edges: HogFlowEdge[];
    actions: HogFlowAction[];
  };

  /** The backend derives the top-level `trigger` field from the `TriggerAction` entry in
   * `actions` — it isn't sent separately on write. */
  export type HogFlowWrite = {
    name: string;
    description?: string;
    status?: HogFlowStatus;
    edges: HogFlowEdge[];
    actions: HogFlowAction[];
    variables?: Array<Record<string, string>>;
  };

  export type PatchedHogFlowWrite = Partial<HogFlowWrite>;

  export type PaginatedHogFlowMinimalList = {
    count: number;
    next: string | null;
    previous: string | null;
    results: HogFlowMinimal[];
  };

  /** RFC 5545 exhaustion: the RRULE's COUNT/UNTIL has been reached and the schedule will not
   * fire again. */
  export type HogFlowScheduleStatus = "active" | "paused" | "completed";

  export type HogFlowSchedule = {
    id: string;
    /** iCalendar RRULE string (e.g. "FREQ=DAILY;INTERVAL=1"). Must produce occurrences at
     * most once per hour. */
    rrule: string;
    starts_at: string;
    timezone: string;
    variables: Record<string, unknown>;
    status: HogFlowScheduleStatus;
    next_run_at: string | null;
    created_at: string;
    updated_at: string;
  };

  export type HogFlowScheduleWrite = {
    rrule: string;
    starts_at: string;
    timezone?: string;
    variables?: Record<string, unknown>;
  };

  export type PatchedHogFlowScheduleWrite = Partial<HogFlowScheduleWrite>;

  export type PaginatedHogFlowScheduleList = {
    count: number;
    next: string | null;
    previous: string | null;
    results: HogFlowSchedule[];
  };

  /** Hand-vendored ahead of #91581 landing. */
  export type HogFlowRunRequest = {
    variables?: Record<string, unknown>;
  };

  /** Hand-vendored ahead of #91581 landing. */
  export type HogFlowRunResponse = {
    status: string;
    invocation_id: string;
  };
}

const hogFlowsListPath = (projectId: string): string =>
  `/api/projects/${projectId}/hog_flows/`;
const hogFlowDetailPath = (projectId: string, hogFlowId: string): string =>
  `/api/projects/${projectId}/hog_flows/${hogFlowId}/`;
const hogFlowRunPath = (projectId: string, hogFlowId: string): string =>
  `/api/projects/${projectId}/hog_flows/${hogFlowId}/run/`;
const hogFlowSchedulesPath = (projectId: string, hogFlowId: string): string =>
  `/api/projects/${projectId}/hog_flows/${hogFlowId}/schedules/`;
const hogFlowScheduleDetailPath = (
  projectId: string,
  hogFlowId: string,
  scheduleId: string,
): string =>
  `/api/projects/${projectId}/hog_flows/${hogFlowId}/schedules/${scheduleId}/`;

function idempotencyHeader(
  idempotencyKey: string | undefined,
): Record<string, string> | undefined {
  return idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined;
}

async function workflowsRequest<T>(
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
    throw new WorkflowsApiError(
      method,
      path,
      response.status,
      await readBody(response),
    );
  }

  return (await parseResponseData(response)) as T;
}

export class WorkflowsApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(method: string, path: string, status: number, body: unknown) {
    super(
      `Workflows API request failed: ${method.toUpperCase()} ${path} [${status}]`,
    );
    this.name = "WorkflowsApiError";
    this.status = status;
    this.body = body;
  }

  /** A human-readable reason extracted from the response body (DRF `detail` or per-field
   * validation errors), or null when the body carries none. */
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
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export async function listHogFlows(
  client: ApiClient,
  projectId: string,
  query?: { limit?: number; offset?: number },
): Promise<WorkflowSchemas.PaginatedHogFlowMinimalList> {
  return workflowsRequest(client, "get", hogFlowsListPath(projectId), {
    query,
  });
}

export async function retrieveHogFlow(
  client: ApiClient,
  projectId: string,
  hogFlowId: string,
): Promise<WorkflowSchemas.HogFlow> {
  return workflowsRequest(
    client,
    "get",
    hogFlowDetailPath(projectId, hogFlowId),
  );
}

export async function createHogFlow(
  client: ApiClient,
  projectId: string,
  body: WorkflowSchemas.HogFlowWrite,
): Promise<WorkflowSchemas.HogFlow> {
  return workflowsRequest(client, "post", hogFlowsListPath(projectId), {
    body,
  });
}

export async function partialUpdateHogFlow(
  client: ApiClient,
  projectId: string,
  hogFlowId: string,
  body: WorkflowSchemas.PatchedHogFlowWrite,
): Promise<WorkflowSchemas.HogFlow> {
  return workflowsRequest(
    client,
    "patch",
    hogFlowDetailPath(projectId, hogFlowId),
    { body },
  );
}

export async function destroyHogFlow(
  client: ApiClient,
  projectId: string,
  hogFlowId: string,
): Promise<void> {
  await workflowsRequest(
    client,
    "delete",
    hogFlowDetailPath(projectId, hogFlowId),
  );
}

/** Fires a schedule-triggered, active workflow immediately. Hand-vendored ahead of #91581
 * landing — see `WorkflowSchemas.HogFlowRunRequest`. */
export async function runHogFlow(
  client: ApiClient,
  projectId: string,
  hogFlowId: string,
  body?: WorkflowSchemas.HogFlowRunRequest,
  idempotencyKey?: string,
): Promise<WorkflowSchemas.HogFlowRunResponse> {
  return workflowsRequest(
    client,
    "post",
    hogFlowRunPath(projectId, hogFlowId),
    {
      body: body ?? {},
      header: idempotencyHeader(idempotencyKey),
    },
  );
}

export async function listHogFlowSchedules(
  client: ApiClient,
  projectId: string,
  hogFlowId: string,
): Promise<WorkflowSchemas.PaginatedHogFlowScheduleList> {
  return workflowsRequest(
    client,
    "get",
    hogFlowSchedulesPath(projectId, hogFlowId),
  );
}

export async function createHogFlowSchedule(
  client: ApiClient,
  projectId: string,
  hogFlowId: string,
  body: WorkflowSchemas.HogFlowScheduleWrite,
): Promise<WorkflowSchemas.HogFlowSchedule> {
  return workflowsRequest(
    client,
    "post",
    hogFlowSchedulesPath(projectId, hogFlowId),
    { body },
  );
}

export async function partialUpdateHogFlowSchedule(
  client: ApiClient,
  projectId: string,
  hogFlowId: string,
  scheduleId: string,
  body: WorkflowSchemas.PatchedHogFlowScheduleWrite,
): Promise<WorkflowSchemas.HogFlowSchedule> {
  return workflowsRequest(
    client,
    "patch",
    hogFlowScheduleDetailPath(projectId, hogFlowId, scheduleId),
    { body },
  );
}

export async function destroyHogFlowSchedule(
  client: ApiClient,
  projectId: string,
  hogFlowId: string,
  scheduleId: string,
): Promise<void> {
  await workflowsRequest(
    client,
    "delete",
    hogFlowScheduleDetailPath(projectId, hogFlowId, scheduleId),
  );
}

export function isCreateTaskAction(
  action: WorkflowSchemas.HogFlowAction,
): action is WorkflowSchemas.CreateTaskAction {
  return (
    action.type === "function" &&
    typeof action.config === "object" &&
    action.config !== null &&
    (action.config as { template_id?: unknown }).template_id ===
      CREATE_TASK_TEMPLATE_ID
  );
}

export function isTriggerAction(
  action: WorkflowSchemas.HogFlowAction,
): action is WorkflowSchemas.TriggerAction {
  return action.type === "trigger";
}

/** Finds the create-task action in a loop-shaped flow, or null if the flow doesn't have exactly
 * one. Cheaper than a full `isLoopShapedHogFlow` check when the caller only needs the action. */
export function findCreateTaskAction(
  actions: WorkflowSchemas.HogFlowAction[],
): WorkflowSchemas.CreateTaskAction | null {
  const matches = actions.filter(isCreateTaskAction);
  return matches.length === 1 ? matches[0] : null;
}

/** A HogFlow this feature can render and edit as a loop: exactly one trigger node with a
 * `schedule` config, exactly one "Create AI task" action, and a single edge wiring the trigger
 * directly to it. Anything else (extra actions, branching, a different trigger type, an edge
 * this feature didn't write) was built or hand-edited outside this feature and is rendered
 * read-only instead of force-fit into the loop form — see `LoopDetailView`. */
export function isLoopShapedHogFlow(
  flow: Pick<WorkflowSchemas.HogFlow, "actions" | "edges">,
): boolean {
  if (flow.actions.length !== 2) return false;
  const trigger = flow.actions.find(isTriggerAction);
  const task = findCreateTaskAction(flow.actions);
  if (!trigger || !task || trigger.config.type !== "schedule") return false;
  return (
    flow.edges.length === 1 &&
    flow.edges[0].from === trigger.id &&
    flow.edges[0].to === task.id
  );
}
