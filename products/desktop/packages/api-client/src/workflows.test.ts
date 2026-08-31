import { describe, expect, it, vi } from "vitest";
import { type ApiClient, createApiClient, type Fetcher } from "./generated";
import {
  createHogFlow,
  createHogFlowSchedule,
  destroyHogFlow,
  findCreateTaskAction,
  isCreateTaskAction,
  isLoopShapedHogFlow,
  isTriggerAction,
  listHogFlows,
  partialUpdateHogFlow,
  partialUpdateHogFlowSchedule,
  retrieveHogFlow,
  runHogFlow,
  type WorkflowSchemas,
  WorkflowsApiError,
} from "./workflows";

const BASE_URL = "https://app.posthog.com";
const PROJECT_ID = "1";
const HOG_FLOW_ID = "flow-abc";
const SCHEDULE_ID = "schedule-abc";

const MINIMAL_HOG_FLOW_WRITE: WorkflowSchemas.HogFlowWrite = {
  name: "My loop",
  status: "active",
  actions: [
    {
      id: "trigger_node",
      name: "Schedule",
      type: "trigger",
      config: { type: "schedule" },
    },
    {
      id: "create_ai_task",
      name: "Create AI task",
      type: "function",
      config: {
        template_id: "template-posthog-create-task",
        inputs: {
          prompt: { value: "Do the thing" },
          non_failure_status_codes: { value: [409] },
        },
      },
    },
  ],
  edges: [{ from: "trigger_node", to: "create_ai_task", type: "continue" }],
};

function fakeFetcher(
  data: unknown,
  status = 200,
): { fetcher: Fetcher; fetchMock: ReturnType<typeof vi.fn> } {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: status < 400,
    status,
    headers: {
      get: (key: string) =>
        key === "content-type" ? "application/json" : null,
    },
    json: () => Promise.resolve(data),
  });
  return { fetcher: { fetch: fetchMock }, fetchMock };
}

describe("workflows client", () => {
  const cases: Array<{
    name: string;
    invoke: (client: ApiClient) => Promise<unknown>;
    method: string;
    path: string;
  }> = [
    {
      name: "listHogFlows",
      invoke: (client) => listHogFlows(client, PROJECT_ID),
      method: "get",
      path: `/api/projects/${PROJECT_ID}/hog_flows/`,
    },
    {
      name: "retrieveHogFlow",
      invoke: (client) => retrieveHogFlow(client, PROJECT_ID, HOG_FLOW_ID),
      method: "get",
      path: `/api/projects/${PROJECT_ID}/hog_flows/${HOG_FLOW_ID}/`,
    },
    {
      name: "createHogFlow",
      invoke: (client) =>
        createHogFlow(client, PROJECT_ID, MINIMAL_HOG_FLOW_WRITE),
      method: "post",
      path: `/api/projects/${PROJECT_ID}/hog_flows/`,
    },
    {
      name: "partialUpdateHogFlow",
      invoke: (client) =>
        partialUpdateHogFlow(client, PROJECT_ID, HOG_FLOW_ID, {
          name: "Renamed",
        }),
      method: "patch",
      path: `/api/projects/${PROJECT_ID}/hog_flows/${HOG_FLOW_ID}/`,
    },
    {
      name: "destroyHogFlow",
      invoke: (client) => destroyHogFlow(client, PROJECT_ID, HOG_FLOW_ID),
      method: "delete",
      path: `/api/projects/${PROJECT_ID}/hog_flows/${HOG_FLOW_ID}/`,
    },
    {
      name: "runHogFlow",
      invoke: (client) => runHogFlow(client, PROJECT_ID, HOG_FLOW_ID),
      method: "post",
      path: `/api/projects/${PROJECT_ID}/hog_flows/${HOG_FLOW_ID}/run/`,
    },
    {
      name: "createHogFlowSchedule",
      invoke: (client) =>
        createHogFlowSchedule(client, PROJECT_ID, HOG_FLOW_ID, {
          rrule: "FREQ=DAILY",
          starts_at: "2026-01-01T09:00:00.000Z",
        }),
      method: "post",
      path: `/api/projects/${PROJECT_ID}/hog_flows/${HOG_FLOW_ID}/schedules/`,
    },
    {
      name: "partialUpdateHogFlowSchedule",
      invoke: (client) =>
        partialUpdateHogFlowSchedule(
          client,
          PROJECT_ID,
          HOG_FLOW_ID,
          SCHEDULE_ID,
          { timezone: "UTC" },
        ),
      method: "patch",
      path: `/api/projects/${PROJECT_ID}/hog_flows/${HOG_FLOW_ID}/schedules/${SCHEDULE_ID}/`,
    },
  ];

  for (const testCase of cases) {
    it(`${testCase.name} calls the right method and path`, async () => {
      const { fetcher, fetchMock } = fakeFetcher({});
      const client = createApiClient(fetcher, BASE_URL);

      await testCase.invoke(client);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const call = fetchMock.mock.calls[0][0];
      expect(call.method).toBe(testCase.method);
      expect(call.path).toBe(testCase.path);
    });
  }

  it("runHogFlow sends an Idempotency-Key header when given one", async () => {
    const { fetcher, fetchMock } = fakeFetcher({
      status: "queued",
      invocation_id: "inv-1",
    });
    const client = createApiClient(fetcher, BASE_URL);

    const result = await runHogFlow(
      client,
      PROJECT_ID,
      HOG_FLOW_ID,
      { variables: { name: "Overridden" } },
      "key-1",
    );

    expect(result).toEqual({ status: "queued", invocation_id: "inv-1" });
    const call = fetchMock.mock.calls[0][0];
    expect(call.parameters.header).toEqual({ "Idempotency-Key": "key-1" });
    expect(call.parameters.body).toEqual({ variables: { name: "Overridden" } });
  });

  it("throws WorkflowsApiError with the parsed body on a non-2xx response", async () => {
    const { fetcher } = fakeFetcher(
      { detail: "Workflow must be active to run. Enable it first." },
      400,
    );
    const client = createApiClient(fetcher, BASE_URL);

    await expect(runHogFlow(client, PROJECT_ID, HOG_FLOW_ID)).rejects.toSatisfy(
      (error: unknown) => {
        expect(error).toBeInstanceOf(WorkflowsApiError);
        expect((error as WorkflowsApiError).status).toBe(400);
        expect((error as WorkflowsApiError).detail).toBe(
          "Workflow must be active to run. Enable it first.",
        );
        return true;
      },
    );
  });
});

describe("isCreateTaskAction / isTriggerAction / findCreateTaskAction", () => {
  const triggerAction: WorkflowSchemas.TriggerAction = {
    id: "trigger_node",
    name: "Schedule",
    type: "trigger",
    config: { type: "schedule" },
  };
  const taskAction: WorkflowSchemas.CreateTaskAction = {
    id: "create_ai_task",
    name: "Create AI task",
    type: "function",
    config: {
      template_id: "template-posthog-create-task",
      inputs: {
        prompt: { value: "Do it" },
        non_failure_status_codes: { value: [409] },
      },
    },
  };
  const otherAction: WorkflowSchemas.OtherAction = {
    id: "other",
    name: "Something else",
    type: "function",
    config: { template_id: "template-slack" },
  };

  it("identifies a create-task action by its template_id, not just its type", () => {
    expect(isCreateTaskAction(taskAction)).toBe(true);
    expect(isCreateTaskAction(otherAction)).toBe(false);
    expect(isCreateTaskAction(triggerAction)).toBe(false);
  });

  it("identifies a trigger action by type", () => {
    expect(isTriggerAction(triggerAction)).toBe(true);
    expect(isTriggerAction(taskAction)).toBe(false);
  });

  it("finds exactly one create-task action, or null otherwise", () => {
    expect(findCreateTaskAction([triggerAction, taskAction])).toBe(taskAction);
    expect(findCreateTaskAction([triggerAction, otherAction])).toBeNull();
    expect(
      findCreateTaskAction([
        triggerAction,
        taskAction,
        { ...taskAction, id: "second" },
      ]),
    ).toBeNull();
  });

  it("recognizes the canonical loop shape: one schedule trigger wired to one create-task action", () => {
    expect(
      isLoopShapedHogFlow({
        actions: [triggerAction, taskAction],
        edges: [
          { from: "trigger_node", to: "create_ai_task", type: "continue" },
        ],
      }),
    ).toBe(true);
  });

  it("rejects a flow with an extra action", () => {
    expect(
      isLoopShapedHogFlow({
        actions: [triggerAction, taskAction, otherAction],
        edges: [
          { from: "trigger_node", to: "create_ai_task", type: "continue" },
        ],
      }),
    ).toBe(false);
  });

  it("rejects a non-schedule trigger", () => {
    expect(
      isLoopShapedHogFlow({
        actions: [{ ...triggerAction, config: { type: "event" } }, taskAction],
        edges: [
          { from: "trigger_node", to: "create_ai_task", type: "continue" },
        ],
      }),
    ).toBe(false);
  });

  it("rejects a flow whose edge doesn't wire the trigger directly to the task action", () => {
    expect(
      isLoopShapedHogFlow({
        actions: [triggerAction, taskAction],
        edges: [
          { from: "create_ai_task", to: "trigger_node", type: "continue" },
        ],
      }),
    ).toBe(false);
  });
});
