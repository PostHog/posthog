import { ApiRequestError } from "@posthog/api-client/fetcher";
import {
  type ApiClient,
  createApiClient,
  type Fetcher,
} from "@posthog/api-client/generated";
import { describe, expect, it, vi } from "vitest";
import { emptyLoopFormValues } from "./loopFormTypes";
import { formValuesToHogFlowWrite } from "./loopHogFlowMapping";
import { createLoopHogFlow, updateLoopHogFlow } from "./loopHogFlowWrites";

type Route = { method: string; path: string };

/** A client whose responses are scripted per method+path, recording the
 * order of requests so a sequence can be asserted. */
function scriptedClient(
  responder: (route: Route) => { status: number; body?: unknown },
): { client: ApiClient; calls: Route[] } {
  const calls: Route[] = [];
  const fetchMock = vi.fn(async (request: { method: string; url: URL }) => {
    const route = { method: request.method, path: request.url.pathname };
    calls.push(route);
    const { status, body } = responder(route);
    if (status >= 400) {
      throw new ApiRequestError(status, JSON.stringify(body ?? {}), body);
    }
    return {
      ok: true,
      status,
      headers: { get: () => "application/json" },
      json: () => Promise.resolve(body ?? {}),
    };
  });
  const fetcher: Fetcher = {
    fetch: fetchMock as unknown as Fetcher["fetch"],
  };
  return { client: createApiClient(fetcher, "https://us.posthog.com"), calls };
}

const FLOW = { id: "flow-1", status: "active", schedules: [] };
const SCHEDULE_ROW = {
  id: "sched-1",
  rrule: "FREQ=DAILY;INTERVAL=1",
  starts_at: "2026-01-01T09:00:00Z",
  timezone: "UTC",
  status: "active",
  next_run_at: null,
  created_at: "",
  updated_at: "",
} as const;

function scheduleWrite(cron = "0 9 * * *") {
  return formValuesToHogFlowWrite(
    {
      ...emptyLoopFormValues(),
      name: "Loop",
      instructions: "Do the thing",
      triggers: [
        {
          key: "t",
          type: "schedule",
          enabled: true,
          config: { cron_expression: cron, timezone: "UTC" },
        },
      ],
    },
    { enabled: true },
  );
}

function githubWrite() {
  return formValuesToHogFlowWrite(
    {
      ...emptyLoopFormValues(),
      name: "Loop",
      instructions: "Do the thing",
      triggers: [
        {
          key: "t",
          type: "github",
          enabled: true,
          config: {
            github_integration_id: 1,
            repository: "example/app",
            events: ["push"],
          },
        },
      ],
    },
    { enabled: true },
  );
}

describe("loopHogFlowWrites", () => {
  it("deletes the new workflow again when its schedule is rejected", async () => {
    const { client, calls } = scriptedClient(({ method, path }) => {
      if (method === "post" && path.endsWith("/schedules/")) {
        return { status: 400, body: { rrule: ["Invalid RRULE."] } };
      }
      return { status: 200, body: FLOW };
    });
    await expect(
      createLoopHogFlow(client, "7", scheduleWrite()),
    ).rejects.toThrow(ApiRequestError);
    expect(calls.map((call) => `${call.method} ${call.path}`)).toEqual([
      "post /api/projects/7/hog_flows/",
      "post /api/projects/7/hog_flows/flow-1/schedules/",
      "delete /api/projects/7/hog_flows/flow-1/",
    ]);
  });

  it("returns the new workflow with its schedule attached", async () => {
    const { client } = scriptedClient(({ method, path }) =>
      method === "post" && path.endsWith("/schedules/")
        ? { status: 200, body: SCHEDULE_ROW }
        : { status: 200, body: FLOW },
    );
    const flow = await createLoopHogFlow(client, "7", scheduleWrite());
    expect(flow.schedules).toEqual([SCHEDULE_ROW]);
  });

  it.each([
    {
      label: "leaves a matching schedule alone",
      write: scheduleWrite("0 9 * * *"),
      existing: [SCHEDULE_ROW],
      expected: ["patch /api/projects/7/hog_flows/flow-1/"],
    },
    {
      label: "updates the schedule in place when the cadence changes",
      write: scheduleWrite("0 17 * * *"),
      existing: [SCHEDULE_ROW],
      expected: [
        "patch /api/projects/7/hog_flows/flow-1/",
        "patch /api/projects/7/hog_flows/flow-1/schedules/sched-1/",
      ],
    },
    {
      label: "creates a schedule for a loop that lost its row",
      write: scheduleWrite(),
      existing: [],
      expected: [
        "patch /api/projects/7/hog_flows/flow-1/",
        "post /api/projects/7/hog_flows/flow-1/schedules/",
      ],
    },
    {
      label: "removes the schedule when the trigger becomes a GitHub event",
      write: githubWrite(),
      existing: [SCHEDULE_ROW],
      expected: [
        "patch /api/projects/7/hog_flows/flow-1/",
        "delete /api/projects/7/hog_flows/flow-1/schedules/sched-1/",
      ],
    },
  ])("$label", async ({ write, existing, expected }) => {
    const { client, calls } = scriptedClient(() => ({
      status: 200,
      body: { ...FLOW, schedules: existing },
    }));
    await updateLoopHogFlow(
      client,
      "7",
      { id: "flow-1", schedules: [...existing] },
      write,
    );
    expect(calls.map((call) => `${call.method} ${call.path}`)).toEqual(
      expected,
    );
  });

  it("does not send status or the origin tag with an edit", async () => {
    let patched: Record<string, unknown> | undefined;
    const fetchMock = vi.fn(
      async (request: { parameters?: { body?: Record<string, unknown> } }) => {
        patched = request.parameters?.body;
        return {
          ok: true,
          status: 200,
          headers: { get: () => "application/json" },
          json: () => Promise.resolve({ ...FLOW, schedules: [SCHEDULE_ROW] }),
        };
      },
    );
    const client = createApiClient(
      { fetch: fetchMock as unknown as Fetcher["fetch"] },
      "https://us.posthog.com",
    );
    await updateLoopHogFlow(
      client,
      "7",
      { id: "flow-1", schedules: [SCHEDULE_ROW] },
      scheduleWrite(),
    );
    const keys = Object.keys(patched ?? {});
    expect(keys).toContain("actions");
    expect(keys).not.toContain("status");
    expect(keys).not.toContain("origin_product");
    expect(patched?.actions).toHaveLength(3);
  });
});
