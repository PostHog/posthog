import { describe, expect, it, vi } from "vitest";
import { type ApiClient, createApiClient, type Fetcher } from "./generated";
import {
  createLoop,
  destroyLoop,
  type LoopSchemas,
  LoopsApiError,
  listLoopRuns,
  listLoops,
  partialUpdateLoop,
  previewLoop,
  retrieveLoop,
  runLoop,
  triggerLoop,
} from "./loops";

const BASE_URL = "https://app.posthog.com";
const PROJECT_ID = "1";
const LOOP_ID = "loop-abc";

const MINIMAL_LOOP_WRITE: LoopSchemas.LoopWrite = {
  name: "My loop",
  instructions: "Summarize failing CI runs.",
  runtime_adapter: "claude",
  model: "claude-sonnet",
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

describe("loops client", () => {
  const cases: Array<{
    name: string;
    invoke: (client: ApiClient) => Promise<unknown>;
    method: string;
    path: string;
  }> = [
    {
      name: "listLoops",
      invoke: (client) => listLoops(client, PROJECT_ID),
      method: "get",
      path: `/api/projects/${PROJECT_ID}/loops/`,
    },
    {
      name: "retrieveLoop",
      invoke: (client) => retrieveLoop(client, PROJECT_ID, LOOP_ID),
      method: "get",
      path: `/api/projects/${PROJECT_ID}/loops/${LOOP_ID}/`,
    },
    {
      name: "createLoop",
      invoke: (client) => createLoop(client, PROJECT_ID, MINIMAL_LOOP_WRITE),
      method: "post",
      path: `/api/projects/${PROJECT_ID}/loops/`,
    },
    {
      name: "partialUpdateLoop",
      invoke: (client) =>
        partialUpdateLoop(client, PROJECT_ID, LOOP_ID, { name: "Renamed" }),
      method: "patch",
      path: `/api/projects/${PROJECT_ID}/loops/${LOOP_ID}/`,
    },
    {
      name: "destroyLoop",
      invoke: (client) => destroyLoop(client, PROJECT_ID, LOOP_ID),
      method: "delete",
      path: `/api/projects/${PROJECT_ID}/loops/${LOOP_ID}/`,
    },
    {
      name: "runLoop",
      invoke: (client) => runLoop(client, PROJECT_ID, LOOP_ID),
      method: "post",
      path: `/api/projects/${PROJECT_ID}/loops/${LOOP_ID}/run/`,
    },
    {
      name: "triggerLoop",
      invoke: (client) => triggerLoop(client, PROJECT_ID, LOOP_ID, {}),
      method: "post",
      path: `/api/projects/${PROJECT_ID}/loops/${LOOP_ID}/trigger/`,
    },
    {
      name: "listLoopRuns",
      invoke: (client) => listLoopRuns(client, PROJECT_ID, LOOP_ID),
      method: "get",
      path: `/api/projects/${PROJECT_ID}/loops/${LOOP_ID}/runs/`,
    },
    {
      name: "previewLoop",
      invoke: (client) => previewLoop(client, PROJECT_ID, LOOP_ID),
      method: "post",
      path: `/api/projects/${PROJECT_ID}/loops/${LOOP_ID}/preview/`,
    },
  ];

  it.each(cases)(
    "$name calls $method $path",
    async ({ invoke, method, path }) => {
      const { fetcher, fetchMock } = fakeFetcher({});
      const client = createApiClient(fetcher, BASE_URL);

      await invoke(client);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const call = fetchMock.mock.calls[0][0];
      expect(call.method).toBe(method);
      expect(call.path).toBe(path);
      expect(call.url.toString()).toBe(`${BASE_URL}${path}`);
    },
  );

  it("returns the parsed response body", async () => {
    const loop = { ...MINIMAL_LOOP_WRITE, id: LOOP_ID };
    const { fetcher } = fakeFetcher(loop);
    const client = createApiClient(fetcher, BASE_URL);

    await expect(retrieveLoop(client, PROJECT_ID, LOOP_ID)).resolves.toEqual(
      loop,
    );
  });

  it("passes cursor and limit through to listLoopRuns as query params", async () => {
    const { fetcher, fetchMock } = fakeFetcher({
      results: [],
      next_cursor: null,
    });
    const client = createApiClient(fetcher, BASE_URL);

    await listLoopRuns(client, PROJECT_ID, LOOP_ID, {
      cursor: "abc",
      limit: 10,
    });

    const call = fetchMock.mock.calls[0][0];
    expect(call.urlSearchParams?.toString()).toBe("cursor=abc&limit=10");
  });

  it("sets the Idempotency-Key header on runLoop when provided", async () => {
    const { fetcher, fetchMock } = fakeFetcher({
      created: true,
      reason: "created",
      task_id: "t1",
      task_run_id: "r1",
    });
    const client = createApiClient(fetcher, BASE_URL);

    await runLoop(client, PROJECT_ID, LOOP_ID, "my-key");

    const call = fetchMock.mock.calls[0][0];
    expect(call.parameters?.header).toEqual({ "Idempotency-Key": "my-key" });
  });

  it("omits the Idempotency-Key header on triggerLoop when not provided", async () => {
    const { fetcher, fetchMock } = fakeFetcher({
      created: false,
      reason: "disabled",
      task_id: null,
      task_run_id: null,
    });
    const client = createApiClient(fetcher, BASE_URL);

    await triggerLoop(client, PROJECT_ID, LOOP_ID, { foo: "bar" });

    const call = fetchMock.mock.calls[0][0];
    expect(call.parameters?.body).toEqual({ foo: "bar" });
    expect(call.parameters?.header).toBeUndefined();
  });

  it("resolves destroyLoop to undefined for a 204 with no body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      headers: { get: () => null },
      json: () => Promise.reject(new Error("no body to parse")),
    });
    const client = createApiClient({ fetch: fetchMock }, BASE_URL);

    await expect(
      destroyLoop(client, PROJECT_ID, LOOP_ID),
    ).resolves.toBeUndefined();
  });

  it("throws when the response is not ok", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      headers: { get: () => null },
    });
    const client = createApiClient({ fetch: fetchMock }, BASE_URL);

    await expect(retrieveLoop(client, PROJECT_ID, "missing")).rejects.toThrow(
      "[404]",
    );
  });

  it("throws LoopsApiError carrying the parsed body on a rejected request", async () => {
    const { fetcher } = fakeFetcher(
      {
        error: "loop_safety_limit",
        code: "max_loops_per_team",
        limit: 100,
        detail: "This project has reached the limit of 100 loops.",
      },
      429,
    );
    const client = createApiClient(fetcher, BASE_URL);

    const error = await createLoop(
      client,
      PROJECT_ID,
      MINIMAL_LOOP_WRITE,
    ).catch((e) => e);

    expect(error).toBeInstanceOf(LoopsApiError);
    expect((error as LoopsApiError).status).toBe(429);
    const safetyLimit = (error as LoopsApiError).safetyLimit;
    expect(safetyLimit?.code).toBe("max_loops_per_team");
    expect(safetyLimit?.detail).toContain("100 loops");
  });

  it("leaves safetyLimit null for a generic (non-limit) error body", async () => {
    const { fetcher } = fakeFetcher({ detail: "Something broke" }, 500);
    const client = createApiClient(fetcher, BASE_URL);

    const error = await createLoop(
      client,
      PROJECT_ID,
      MINIMAL_LOOP_WRITE,
    ).catch((e) => e);

    expect(error).toBeInstanceOf(LoopsApiError);
    expect((error as LoopsApiError).safetyLimit).toBeNull();
  });

  it.each([
    {
      name: "DRF detail string",
      body: { detail: "Not found." },
      expected: "Not found.",
    },
    {
      name: "field validation errors",
      body: {
        name: ["This field may not be blank."],
        triggers: ["Invalid cron expression."],
      },
      expected:
        "name: This field may not be blank.\ntriggers: Invalid cron expression.",
    },
    {
      name: "plain string body",
      body: "upstream unavailable",
      expected: "upstream unavailable",
    },
    { name: "null body", body: null, expected: null },
    { name: "array body", body: ["nope"], expected: null },
    {
      name: "body with no readable messages",
      body: { code: 42, nested: { detail: "hidden" } },
      expected: null,
    },
  ])("detail extracts $name", ({ body, expected }) => {
    const error = new LoopsApiError("post", "/loops/", 400, body);
    expect(error.detail).toBe(expected);
  });
});
