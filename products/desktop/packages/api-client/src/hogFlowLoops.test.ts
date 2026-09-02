import { describe, expect, it, vi } from "vitest";
import { ApiRequestError } from "./fetcher";
import { type ApiClient, createApiClient, type Fetcher } from "./generated";
import {
  createHogFlow,
  createHogFlowSchedule,
  deleteHogFlow,
  deleteHogFlowSchedule,
  type HogFlowLoopBody,
  hogFlowRequestDetail,
  listHogFlowTasks,
  listLoopHogFlows,
  patchHogFlow,
  retrieveHogFlow,
  runHogFlow,
  updateHogFlowSchedule,
} from "./hogFlowLoops";

function fakeClient(data: unknown = {}): {
  client: ApiClient;
  fetchMock: ReturnType<typeof vi.fn>;
} {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    headers: {
      get: (key: string) =>
        key === "content-type" ? "application/json" : null,
    },
    json: () => Promise.resolve(data),
  });
  const fetcher: Fetcher = { fetch: fetchMock };
  const client = createApiClient(fetcher, "https://us.posthog.com");
  return { client, fetchMock };
}

const BODY: HogFlowLoopBody = {
  name: "Loop",
  description: "",
  status: "active",
  origin_product: "loops",
  exit_condition: "exit_only_at_end",
  actions: [],
  edges: [],
};

const SCHEDULE = {
  rrule: "FREQ=DAILY;BYHOUR=9;BYMINUTE=0;BYSECOND=0",
  starts_at: "2026-09-02T09:00:00.000Z",
  timezone: "UTC",
};

describe("hogFlowLoops requests", () => {
  it.each([
    {
      name: "lists only loop-tagged workflows",
      call: (client: ApiClient) => listLoopHogFlows(client, "7"),
      method: "get",
      url: "https://us.posthog.com/api/projects/7/hog_flows/",
      query: "origin_product=loops&limit=100",
    },
    {
      name: "retrieves one workflow",
      call: (client: ApiClient) => retrieveHogFlow(client, "7", "flow-1"),
      method: "get",
      url: "https://us.posthog.com/api/projects/7/hog_flows/flow-1/",
    },
    {
      name: "creates a workflow",
      call: (client: ApiClient) => createHogFlow(client, "7", BODY),
      method: "post",
      url: "https://us.posthog.com/api/projects/7/hog_flows/",
      body: BODY,
    },
    {
      name: "patches a workflow",
      call: (client: ApiClient) =>
        patchHogFlow(client, "7", "flow-1", { status: "draft" }),
      method: "patch",
      url: "https://us.posthog.com/api/projects/7/hog_flows/flow-1/",
      body: { status: "draft" },
    },
    {
      name: "deletes a workflow",
      call: (client: ApiClient) => deleteHogFlow(client, "7", "flow-1"),
      method: "delete",
      url: "https://us.posthog.com/api/projects/7/hog_flows/flow-1/",
    },
    {
      name: "creates a schedule",
      call: (client: ApiClient) =>
        createHogFlowSchedule(client, "7", "flow-1", SCHEDULE),
      method: "post",
      url: "https://us.posthog.com/api/projects/7/hog_flows/flow-1/schedules/",
      body: SCHEDULE,
    },
    {
      name: "updates a schedule",
      call: (client: ApiClient) =>
        updateHogFlowSchedule(client, "7", "flow-1", "sched-1", SCHEDULE),
      method: "patch",
      url: "https://us.posthog.com/api/projects/7/hog_flows/flow-1/schedules/sched-1/",
      body: SCHEDULE,
    },
    {
      name: "deletes a schedule",
      call: (client: ApiClient) =>
        deleteHogFlowSchedule(client, "7", "flow-1", "sched-1"),
      method: "delete",
      url: "https://us.posthog.com/api/projects/7/hog_flows/flow-1/schedules/sched-1/",
    },
    {
      name: "lists the tasks a workflow created, newest first",
      call: (client: ApiClient) =>
        listHogFlowTasks(client, "7", "flow-1", { limit: 10 }),
      method: "get",
      url: "https://us.posthog.com/api/projects/7/tasks/",
      query: "hog_flow_id=flow-1&limit=10&ordering=-created_at",
    },
  ])("$name", async ({ call, method, url, query, body }) => {
    const { client, fetchMock } = fakeClient();
    await call(client);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const request = fetchMock.mock.calls[0][0];
    expect(request.method).toBe(method);
    expect(request.url.toString()).toBe(url);
    expect(request.urlSearchParams?.toString() ?? "").toBe(query ?? "");
    if (body) {
      expect(request.parameters?.body).toEqual(body);
    }
  });

  it("sends the idempotency key with a run request", async () => {
    const { client, fetchMock } = fakeClient({
      status: "queued",
      invocation_id: "inv-1",
    });
    const result = await runHogFlow(client, "7", "flow-1", "key-123");
    expect(result.invocation_id).toBe("inv-1");
    const request = fetchMock.mock.calls[0][0];
    expect(request.url.toString()).toBe(
      "https://us.posthog.com/api/projects/7/hog_flows/flow-1/run/",
    );
    expect(request.parameters?.header).toEqual({
      "Idempotency-Key": "key-123",
    });
  });

  it.each([
    [
      "a DRF detail",
      { detail: "Workflow must be active to run." },
      "Workflow must be active to run.",
    ],
    [
      "a nested serializer rejection",
      { actions: [{ inputs: { prompt: ["Instructions are required."] } }] },
      "Instructions are required.",
    ],
    ["a body with no message", { count: 3 }, null],
  ])("reads %s out of a failed request", (_label, body, expected) => {
    const error = new ApiRequestError(400, JSON.stringify(body), body);
    expect(hogFlowRequestDetail(error)).toBe(expected);
  });

  it("ignores errors that did not come from a request", () => {
    expect(hogFlowRequestDetail(new Error("offline"))).toBeNull();
  });
});
