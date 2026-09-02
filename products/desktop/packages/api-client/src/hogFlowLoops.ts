import { ApiRequestError } from "./fetcher";
import type { ApiClient, Schemas } from "./generated";

/**
 * Requests behind a workflow-backed loop: the `hog_flows` endpoints Desktop
 * Loops read and write when `loops-hog-flows` is on, plus the tasks list that
 * serves as the loop's run history.
 */

export const LOOPS_ORIGIN_PRODUCT = "loops";

export type HogFlowLoopStatus = Extract<
  Schemas.HogFlowStateEnum,
  "active" | "draft"
>;

/** The fields a loop writes on a workflow. Everything else keeps its default. */
export interface HogFlowLoopBody {
  name: string;
  description: string;
  status: HogFlowLoopStatus;
  origin_product: typeof LOOPS_ORIGIN_PRODUCT;
  exit_condition: "exit_only_at_end";
  actions: Schemas.HogFlowAction[];
  edges: Schemas.HogFlowEdge[];
}

export interface HogFlowScheduleWrite {
  rrule: string;
  starts_at: string;
  timezone: string;
}

const HOG_FLOWS_LIST_LIMIT = 100;

export async function listLoopHogFlows(
  client: ApiClient,
  projectId: string,
): Promise<Schemas.PaginatedHogFlowMinimalList> {
  return client.get("/api/projects/{project_id}/hog_flows/", {
    path: { project_id: projectId },
    query: {
      origin_product: LOOPS_ORIGIN_PRODUCT,
      limit: HOG_FLOWS_LIST_LIMIT,
    },
  });
}

export async function retrieveHogFlow(
  client: ApiClient,
  projectId: string,
  hogFlowId: string,
): Promise<Schemas.HogFlow> {
  return client.get("/api/projects/{project_id}/hog_flows/{id}/", {
    path: { project_id: projectId, id: hogFlowId },
  });
}

// The generated create/patch bodies are the read schema, which carries server
// owned fields (id, version, timestamps). The loop body is the writable subset.
export async function createHogFlow(
  client: ApiClient,
  projectId: string,
  body: HogFlowLoopBody,
): Promise<Schemas.HogFlow> {
  return client.post("/api/projects/{project_id}/hog_flows/", {
    path: { project_id: projectId },
    body: body as unknown as Schemas.HogFlow,
  });
}

export async function patchHogFlow(
  client: ApiClient,
  projectId: string,
  hogFlowId: string,
  body: Partial<HogFlowLoopBody>,
): Promise<Schemas.HogFlow> {
  return client.patch("/api/projects/{project_id}/hog_flows/{id}/", {
    path: { project_id: projectId, id: hogFlowId },
    body: body as Schemas.PatchedHogFlowUpdate,
  });
}

export async function deleteHogFlow(
  client: ApiClient,
  projectId: string,
  hogFlowId: string,
): Promise<void> {
  await client.delete("/api/projects/{project_id}/hog_flows/{id}/", {
    path: { project_id: projectId, id: hogFlowId },
  });
}

export async function createHogFlowSchedule(
  client: ApiClient,
  projectId: string,
  hogFlowId: string,
  body: HogFlowScheduleWrite,
): Promise<Schemas.HogFlowSchedule> {
  return client.post("/api/projects/{project_id}/hog_flows/{id}/schedules/", {
    path: { project_id: projectId, id: hogFlowId },
    body: body as unknown as Schemas.HogFlowSchedule,
  });
}

export async function updateHogFlowSchedule(
  client: ApiClient,
  projectId: string,
  hogFlowId: string,
  scheduleId: string,
  body: HogFlowScheduleWrite,
): Promise<Schemas.HogFlowSchedule> {
  return client.patch(
    "/api/projects/{project_id}/hog_flows/{id}/schedules/{schedule_id}/",
    {
      path: { project_id: projectId, id: hogFlowId, schedule_id: scheduleId },
      body: body as Schemas.PatchedHogFlowSchedule,
    },
  );
}

export async function deleteHogFlowSchedule(
  client: ApiClient,
  projectId: string,
  hogFlowId: string,
  scheduleId: string,
): Promise<void> {
  await client.delete(
    "/api/projects/{project_id}/hog_flows/{id}/schedules/{schedule_id}/",
    {
      path: { project_id: projectId, id: hogFlowId, schedule_id: scheduleId },
    },
  );
}

/** Fires a schedule-triggered workflow now. The key dedupes a retry of the
 * same click: the server returns the first run instead of queueing a second. */
export async function runHogFlow(
  client: ApiClient,
  projectId: string,
  hogFlowId: string,
  idempotencyKey: string,
): Promise<Schemas.HogFlowRunResponse> {
  // The endpoint declares no header parameters, so the generated type has no
  // slot for one; the fetcher still forwards `header` at runtime. A variable
  // sidesteps the object-literal excess property check without a cast.
  const params = {
    path: { project_id: projectId, id: hogFlowId },
    body: {},
    header: { "Idempotency-Key": idempotencyKey },
  };
  return client.post("/api/projects/{project_id}/hog_flows/{id}/run/", params);
}

export async function listHogFlowTasks(
  client: ApiClient,
  projectId: string,
  hogFlowId: string,
  options: { limit: number },
): Promise<Schemas.PaginatedTaskDetailDTOList> {
  return client.get("/api/projects/{project_id}/tasks/", {
    path: { project_id: projectId },
    query: {
      hog_flow_id: hogFlowId,
      limit: options.limit,
      ordering: "-created_at",
    },
  });
}

function firstString(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = firstString(item);
      if (found) return found;
    }
    return null;
  }
  if (value && typeof value === "object") {
    for (const item of Object.values(value)) {
      const found = firstString(item);
      if (found) return found;
    }
  }
  return null;
}

/**
 * A readable reason from a failed workflow request. DRF puts a plain
 * rejection under `detail`; a serializer rejection nests messages under field
 * names (`{"actions": [{"inputs": {"prompt": ["..."]}}]}`), so the first
 * string anywhere in the body is the message a person can act on.
 */
export function hogFlowRequestDetail(error: unknown): string | null {
  if (!(error instanceof ApiRequestError)) return null;
  const body = error.body;
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return firstString(body);
}
