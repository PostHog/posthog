import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CloudTaskEvent } from "./schemas";

const mockNetFetch = vi.hoisted(() => vi.fn());
const mockStreamFetch = vi.hoisted(() => vi.fn());
const mockStreamTokenFetch = vi.hoisted(() => vi.fn());

// The service now uses global fetch for BOTH authenticated API calls (JSON)
// and SSE streaming. The two used to be distinct (net.fetch vs global fetch).
// Route by URL: /stream_token/ → token mock (read-leg resolution), the stream leg
// (Django /stream/ or proxy /v1/runs/:run/stream) → stream mock, everything else → API mock.
// The token mock has a Django-path default so existing fixtures (which never set it) are untouched.
const fetchRouter = vi.hoisted(() =>
  vi.fn((input: string | Request, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.url;
    const impl = url.includes("/stream_token/")
      ? mockStreamTokenFetch
      : /\/stream(\/|\?|$)/.test(url)
        ? mockStreamFetch
        : mockNetFetch;
    return impl(input, init);
  }),
);

import { CloudTaskService } from "./cloud-task";

const mockAuthService = {
  authenticatedFetch: vi.fn(),
  getCloudContext: vi.fn(),
};

function createJsonResponse(
  data: unknown,
  status = 200,
  headers?: Record<string, string>,
): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...(headers ?? {}) },
  });
}

function createSseResponse(payload: string, status = 200): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(payload));
      controller.close();
    },
  });

  return new Response(stream, {
    status,
    headers: { "Content-Type": "text/event-stream" },
  });
}

function createOpenSseResponse(payload: string, status = 200): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(payload));
    },
  });

  return new Response(stream, {
    status,
    headers: { "Content-Type": "text/event-stream" },
  });
}

async function waitFor(
  predicate: () => boolean,
  timeoutMs = 2_000,
): Promise<void> {
  const start = Date.now();
  while (!predicate()) {
    if (Date.now() - start > timeoutMs) {
      throw new Error("Timed out waiting for condition");
    }
    if (vi.isFakeTimers()) {
      await vi.advanceTimersByTimeAsync(10);
    } else {
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
  }
}

describe("CloudTaskService", () => {
  let service: CloudTaskService;

  beforeEach(() => {
    const scopedLog = {
      debug: vi.fn(),
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
    };
    const loggerMock = { ...scopedLog, scope: vi.fn(() => scopedLog) };
    const analyticsMock = { track: vi.fn() };
    service = new CloudTaskService(
      mockAuthService as never,
      analyticsMock as never,
      loggerMock,
    );
    mockNetFetch.mockReset();
    mockStreamFetch.mockReset();
    mockStreamTokenFetch.mockReset();
    // Default read-leg resolution: no proxy URL, so the stream reads from Django directly.
    // A resolving stream_token endpoint implies the durable-stream contract (stream-end);
    // legacy-mode tests override this with a 404 to model old servers.
    mockStreamTokenFetch.mockImplementation(() =>
      Promise.resolve(
        createJsonResponse({ token: "test-token", stream_base_url: null }),
      ),
    );
    mockAuthService.authenticatedFetch.mockReset();
    mockAuthService.getCloudContext.mockReset();
    mockAuthService.getCloudContext.mockResolvedValue({
      apiHost: "https://us.posthog.com",
      teamId: 2,
    });
    vi.stubGlobal("fetch", fetchRouter);

    mockAuthService.authenticatedFetch.mockImplementation(
      async (input: string | Request, init?: RequestInit) => {
        return fetchRouter(input, {
          ...init,
          headers: {
            ...(init?.headers ?? {}),
            Authorization: "Bearer token",
          },
        });
      },
    );
  });

  afterEach(() => {
    service.unwatchAll();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("emits a replayed permission_request frame only once", async () => {
    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    mockNetFetch
      .mockResolvedValueOnce(
        createJsonResponse({
          id: "run-1",
          status: "in_progress",
          stage: "build",
          output: null,
          error_message: null,
          branch: "main",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      )
      .mockResolvedValue(
        createJsonResponse([], 200, { "X-Has-More": "false" }),
      );

    const frame =
      'id: 5\ndata: {"type":"permission_request","requestId":"req-1","toolCall":{"toolCallId":"tool-1"},"options":[]}\n\n';
    const trailingEntry =
      'id: 6\ndata: {"type":"notification","timestamp":"2026-01-01T00:00:02Z","notification":{"jsonrpc":"2.0","method":"_posthog/console","params":{"sessionId":"run-1","level":"info","message":"after replay"}}}\n\n';
    // The durable stream re-sends the tail on reconnect/replay — the same
    // frame arriving twice must not re-surface the question a second time.
    mockStreamFetch.mockResolvedValueOnce(
      createOpenSseResponse(frame + frame + trailingEntry),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(() =>
      updates.some((u) => (u as { kind?: string }).kind === "logs"),
    );

    const permissionUpdates = updates.filter(
      (u) => (u as { kind?: string }).kind === "permission_request",
    );
    expect(permissionUpdates).toEqual([
      {
        taskId: "task-1",
        runId: "run-1",
        kind: "permission_request",
        requestId: "req-1",
        toolCall: { toolCallId: "tool-1" },
        options: [],
      },
    ]);
  });

  it("bootstraps paged backlog for active runs and drains deduped live SSE entries", async () => {
    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    mockNetFetch
      .mockResolvedValueOnce(
        createJsonResponse({
          id: "run-1",
          status: "in_progress",
          stage: "build",
          output: null,
          error_message: null,
          branch: "main",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      )
      .mockResolvedValueOnce(
        createJsonResponse(
          [
            {
              type: "notification",
              timestamp: "2026-01-01T00:00:00Z",
              notification: {
                jsonrpc: "2.0",
                method: "_posthog/console",
                params: {
                  sessionId: "run-1",
                  level: "info",
                  message: "older history",
                },
              },
            },
          ],
          200,
          { "X-Has-More": "true" },
        ),
      )
      .mockResolvedValueOnce(
        createJsonResponse(
          [
            {
              type: "notification",
              timestamp: "2026-01-01T00:00:01Z",
              notification: {
                jsonrpc: "2.0",
                method: "_posthog/console",
                params: {
                  sessionId: "run-1",
                  level: "info",
                  message: "hello",
                },
              },
            },
          ],
          200,
          { "X-Has-More": "false" },
        ),
      );

    mockStreamFetch.mockResolvedValueOnce(
      createOpenSseResponse(
        'id: 1\ndata: {"type":"notification","timestamp":"2026-01-01T00:00:01Z","notification":{"jsonrpc":"2.0","method":"_posthog/console","params":{"sessionId":"run-1","level":"info","message":"hello"}}}\n\nid: 2\ndata: {"type":"notification","timestamp":"2026-01-01T00:00:02Z","notification":{"jsonrpc":"2.0","method":"_posthog/console","params":{"sessionId":"run-1","level":"info","message":"live tail"}}}\n\n',
      ),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(() => updates.length >= 2);

    expect(updates).toEqual([
      {
        taskId: "task-1",
        runId: "run-1",
        kind: "snapshot",
        newEntries: [
          {
            type: "notification",
            timestamp: "2026-01-01T00:00:00Z",
            notification: {
              jsonrpc: "2.0",
              method: "_posthog/console",
              params: {
                sessionId: "run-1",
                level: "info",
                message: "older history",
              },
            },
          },
          {
            type: "notification",
            timestamp: "2026-01-01T00:00:01Z",
            notification: {
              jsonrpc: "2.0",
              method: "_posthog/console",
              params: {
                sessionId: "run-1",
                level: "info",
                message: "hello",
              },
            },
          },
        ],
        totalEntryCount: 2,
        status: "in_progress",
        stage: "build",
        output: null,
        errorMessage: null,
        branch: "main",
      },
      {
        taskId: "task-1",
        runId: "run-1",
        kind: "logs",
        newEntries: [
          {
            type: "notification",
            timestamp: "2026-01-01T00:00:02Z",
            notification: {
              jsonrpc: "2.0",
              method: "_posthog/console",
              params: {
                sessionId: "run-1",
                level: "info",
                message: "live tail",
              },
            },
          },
        ],
        totalEntryCount: 3,
      },
    ]);

    expect(mockStreamFetch).toHaveBeenCalledWith(
      "https://app.example.com/api/projects/2/tasks/task-1/runs/run-1/stream/?start=latest",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer token",
          Accept: "text/event-stream",
        }),
      }),
    );
  });

  it("drops a re-delivered log entry with a duplicate stream id", async () => {
    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    mockNetFetch
      .mockResolvedValueOnce(
        createJsonResponse({
          id: "run-1",
          status: "in_progress",
          stage: null,
          output: null,
          error_message: null,
          branch: "main",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      )
      .mockResolvedValueOnce(
        createJsonResponse([], 200, { "X-Has-More": "false" }),
      );

    const consoleEntry = (message: string) =>
      `data: {"type":"notification","timestamp":"2026-01-01T00:00:01Z","notification":{"jsonrpc":"2.0","method":"_posthog/console","params":{"sessionId":"run-1","level":"info","message":"${message}"}}}`;

    // The durable stream re-sends the tail by id on reconnect/replay. Here id 1
    // arrives twice; the second copy must be dropped so the entry is delivered
    // — and counted — exactly once (the fix for duplicate transcript entries and
    // back-to-back completion notifications).
    mockStreamFetch.mockResolvedValueOnce(
      createOpenSseResponse(
        `id: 1\n${consoleEntry("first")}\n\nid: 1\n${consoleEntry("first")}\n\nid: 2\n${consoleEntry("second")}\n\n`,
      ),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(() =>
      updates.some(
        (u) =>
          (u as { kind?: string; totalEntryCount?: number }).kind === "logs" &&
          ((u as { totalEntryCount?: number }).totalEntryCount ?? 0) >= 2,
      ),
    );

    const messages = updates
      .filter((u) => (u as { kind?: string }).kind === "logs")
      .flatMap(
        (u) =>
          (u as { newEntries: Array<{ notification?: { params?: unknown } }> })
            .newEntries,
      )
      .map(
        (entry) =>
          (entry.notification?.params as { message?: string } | undefined)
            ?.message,
      );

    // id 1 delivered once (not twice), id 2 delivered once, order preserved.
    expect(messages).toEqual(["first", "second"]);
  });

  it("delivers an id-colliding entry after a retry resets the watcher", async () => {
    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    // Route by URL: the initial watch and the retry-triggered rebuild each
    // fetch run detail and history, plus post-bootstrap status verification.
    mockNetFetch.mockImplementation((input: string | Request) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/session_logs/")) {
        return Promise.resolve(
          createJsonResponse([], 200, { "X-Has-More": "false" }),
        );
      }
      return Promise.resolve(
        createJsonResponse({
          id: "run-1",
          status: "in_progress",
          stage: null,
          output: null,
          error_message: null,
          branch: "main",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      );
    });

    const consoleEntry = (message: string) =>
      `data: {"type":"notification","timestamp":"2026-01-01T00:00:01Z","notification":{"jsonrpc":"2.0","method":"_posthog/console","params":{"sessionId":"run-1","level":"info","message":"${message}"}}}`;

    // The rebuilt connection re-resolves the read leg, so its id space is
    // unrelated to the first connection's: id 1 here is a different entry.
    mockStreamFetch
      .mockResolvedValueOnce(
        createOpenSseResponse(`id: 1\n${consoleEntry("before retry")}\n\n`),
      )
      .mockResolvedValueOnce(
        createOpenSseResponse(`id: 1\n${consoleEntry("after retry")}\n\n`),
      );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    const messages = () =>
      updates
        .filter((u) => (u as { kind?: string }).kind === "logs")
        .flatMap(
          (u) =>
            (
              u as {
                newEntries: Array<{ notification?: { params?: unknown } }>;
              }
            ).newEntries,
        )
        .map(
          (entry) =>
            (entry.notification?.params as { message?: string } | undefined)
              ?.message,
        );

    await waitFor(() => messages().includes("before retry"));

    await service.retry("task-1", "run-1");

    // An id retained across the reset would false-match the new connection's
    // id 1 and silently drop this entry before it is counted or emitted.
    await waitFor(() => messages().includes("after retry"));
    expect(messages()).toEqual(["before retry", "after retry"]);
  });

  it("reconnects with Last-Event-ID after a stream error", async () => {
    vi.useFakeTimers();

    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    mockNetFetch
      .mockResolvedValueOnce(
        createJsonResponse({
          id: "run-1",
          status: "in_progress",
          stage: null,
          output: null,
          error_message: null,
          branch: "main",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      )
      .mockResolvedValueOnce(
        createJsonResponse([], 200, { "X-Has-More": "false" }),
      );

    mockStreamFetch
      .mockResolvedValueOnce(
        createSseResponse(
          'id: 1\ndata: {"type":"notification","timestamp":"2026-01-01T00:00:01Z","notification":{"jsonrpc":"2.0","method":"_posthog/console","params":{"sessionId":"run-1","level":"info","message":"hello"}}}\n\nevent: error\ndata: {"error":"boom"}\n\n',
        ),
      )
      .mockResolvedValueOnce(
        createOpenSseResponse(
          'id: 2\ndata: {"type":"notification","timestamp":"2026-01-01T00:00:02Z","notification":{"jsonrpc":"2.0","method":"_posthog/console","params":{"sessionId":"run-1","level":"info","message":"again"}}}\n\n',
        ),
      );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await vi.advanceTimersByTimeAsync(2_000);
    await waitFor(() => updates.length >= 2);

    expect(mockStreamFetch).toHaveBeenNthCalledWith(
      2,
      "https://app.example.com/api/projects/2/tasks/task-1/runs/run-1/stream/",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer token",
          Accept: "text/event-stream",
          "Last-Event-ID": "1",
        }),
      }),
    );
  });

  it("emits sandbox liveness from run detail when retrying a live watcher", async () => {
    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    mockNetFetch
      .mockResolvedValueOnce(
        createJsonResponse({
          id: "run-1",
          status: "in_progress",
          stage: null,
          output: null,
          state: { sandbox_alive: true },
          error_message: null,
          branch: "main",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      )
      .mockResolvedValueOnce(
        createJsonResponse([], 200, { "X-Has-More": "false" }),
      )
      .mockResolvedValueOnce(
        createJsonResponse({
          id: "run-1",
          status: "in_progress",
          stage: null,
          output: null,
          state: { sandbox_alive: false },
          error_message: null,
          branch: "main",
          updated_at: "2026-01-01T00:01:00Z",
        }),
      );

    mockStreamFetch
      .mockResolvedValueOnce(createOpenSseResponse(""))
      .mockResolvedValueOnce(createOpenSseResponse(""));

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(() =>
      updates.some(
        (update) =>
          typeof update === "object" &&
          update !== null &&
          (update as { kind?: string; sandboxAlive?: boolean }).kind ===
            "snapshot" &&
          (update as { sandboxAlive?: boolean }).sandboxAlive === true,
      ),
    );

    await service.retry("task-1", "run-1");

    await waitFor(() =>
      updates.some(
        (update) =>
          typeof update === "object" &&
          update !== null &&
          (update as { kind?: string; sandboxAlive?: boolean }).kind ===
            "status" &&
          (update as { sandboxAlive?: boolean }).sandboxAlive === false,
      ),
    );
  });

  it("replays a current snapshot when a subscriber attaches to an existing watcher", async () => {
    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    const historicalEntry = {
      type: "notification",
      timestamp: "2026-01-01T00:00:00Z",
      notification: {
        jsonrpc: "2.0",
        method: "_posthog/console",
        params: {
          sessionId: "run-1",
          level: "info",
          message: "older history",
        },
      },
    };
    const liveEntry = {
      type: "notification",
      timestamp: "2026-01-01T00:00:01Z",
      notification: {
        jsonrpc: "2.0",
        method: "_posthog/console",
        params: {
          sessionId: "run-1",
          level: "info",
          message: "live tail",
        },
      },
    };

    const runResponse = {
      id: "run-1",
      status: "in_progress",
      stage: "build",
      output: null,
      error_message: null,
      branch: "main",
      updated_at: "2026-01-01T00:00:00Z",
    };

    mockNetFetch
      .mockResolvedValueOnce(createJsonResponse(runResponse))
      .mockResolvedValueOnce(
        createJsonResponse([historicalEntry], 200, { "X-Has-More": "false" }),
      )
      .mockResolvedValueOnce(createJsonResponse(runResponse))
      .mockResolvedValueOnce(
        createJsonResponse([historicalEntry], 200, { "X-Has-More": "false" }),
      );

    mockStreamFetch.mockResolvedValueOnce(
      createOpenSseResponse(`id: 1\ndata: ${JSON.stringify(liveEntry)}\n\n`),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(() => updates.length >= 2);

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(() =>
      updates.some(
        (update) =>
          typeof update === "object" &&
          update !== null &&
          (update as { kind?: string; totalEntryCount?: number }).kind ===
            "snapshot" &&
          (update as { totalEntryCount?: number }).totalEntryCount === 2,
      ),
    );

    const replayedSnapshot = updates.find(
      (update) =>
        typeof update === "object" &&
        update !== null &&
        (update as { kind?: string; totalEntryCount?: number }).kind ===
          "snapshot" &&
        (update as { totalEntryCount?: number }).totalEntryCount === 2,
    );

    expect(replayedSnapshot).toEqual({
      taskId: "task-1",
      runId: "run-1",
      kind: "snapshot",
      newEntries: [historicalEntry, liveEntry],
      totalEntryCount: 2,
      status: "in_progress",
      stage: "build",
      output: null,
      errorMessage: null,
      branch: "main",
    });

    const getWatcherEmittedEntryCount = (): number => {
      const watcher = (
        service as unknown as {
          watchers: Map<string, { emittedLogEntries: unknown[] }>;
        }
      ).watchers.get("task-1:run-1");
      return watcher?.emittedLogEntries.length ?? 0;
    };

    expect(getWatcherEmittedEntryCount()).toBe(1);

    mockNetFetch.mockResolvedValueOnce(
      createJsonResponse([historicalEntry, liveEntry], 200, {
        "X-Has-More": "false",
      }),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(() => getWatcherEmittedEntryCount() === 0);
  });

  it("ignores keepalive SSE events while keeping the stream open", async () => {
    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    mockNetFetch
      .mockResolvedValueOnce(
        createJsonResponse({
          id: "run-1",
          status: "in_progress",
          stage: "build",
          output: null,
          error_message: null,
          branch: "main",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      )
      .mockResolvedValueOnce(
        createJsonResponse([], 200, { "X-Has-More": "false" }),
      );

    mockStreamFetch.mockResolvedValueOnce(
      createOpenSseResponse(
        'event: keepalive\ndata: {"type":"keepalive"}\n\nid: 2\ndata: {"type":"notification","timestamp":"2026-01-01T00:00:02Z","notification":{"jsonrpc":"2.0","method":"_posthog/console","params":{"sessionId":"run-1","level":"info","message":"live tail"}}}\n\n',
      ),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(() => updates.length >= 2);

    expect(updates).toEqual([
      {
        taskId: "task-1",
        runId: "run-1",
        kind: "snapshot",
        newEntries: [],
        totalEntryCount: 0,
        status: "in_progress",
        stage: "build",
        output: null,
        errorMessage: null,
        branch: "main",
      },
      {
        taskId: "task-1",
        runId: "run-1",
        kind: "logs",
        newEntries: [
          {
            type: "notification",
            timestamp: "2026-01-01T00:00:02Z",
            notification: {
              jsonrpc: "2.0",
              method: "_posthog/console",
              params: {
                sessionId: "run-1",
                level: "info",
                message: "live tail",
              },
            },
          },
        ],
        totalEntryCount: 1,
      },
    ]);
  });

  it("reconnects after clean stream completion when the run remains active", async () => {
    vi.useFakeTimers();

    const updates: unknown[] = [];
    const prUrl = "https://github.com/PostHog/code/pull/123";
    let statusFetchCount = 0;
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    const createInProgressRun = (output: Record<string, unknown> | null) =>
      createJsonResponse({
        id: "run-1",
        status: "in_progress",
        stage: "build",
        output,
        error_message: null,
        branch: "main",
        updated_at: output ? "2026-01-01T00:00:01Z" : "2026-01-01T00:00:00Z",
      });

    mockNetFetch.mockImplementation((input: string | Request) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/session_logs/")) {
        return Promise.resolve(
          createJsonResponse([], 200, { "X-Has-More": "false" }),
        );
      }

      statusFetchCount += 1;
      return Promise.resolve(
        createInProgressRun(statusFetchCount === 1 ? null : { pr_url: prUrl }),
      );
    });

    mockStreamFetch.mockImplementation(() =>
      Promise.resolve(createSseResponse("")),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(() => mockStreamFetch.mock.calls.length === 1);
    await waitFor(() => mockStreamFetch.mock.calls.length >= 7, 20_000);

    expect(updates).toContainEqual(
      expect.objectContaining({
        taskId: "task-1",
        runId: "run-1",
        status: "in_progress",
        output: { pr_url: prUrl },
      }),
    );
    expect(
      updates.some(
        (update) =>
          typeof update === "object" &&
          update !== null &&
          (update as { kind?: string }).kind === "error",
      ),
    ).toBe(false);

    expect(
      (
        service as unknown as {
          watchers: Map<string, unknown>;
        }
      ).watchers.has("task-1:run-1"),
    ).toBe(true);
  });

  it("stops without reconnecting when the server emits stream-end on a non-terminal run", async () => {
    vi.useFakeTimers();

    // Run status stays non-terminal the whole time. Pre-durable-contract, a clean EOF on a
    // non-terminal run reconnects (see the test above); the stream-end sentinel must override that.
    mockNetFetch.mockImplementation((input: string | Request) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/session_logs/")) {
        return Promise.resolve(
          createJsonResponse([], 200, { "X-Has-More": "false" }),
        );
      }
      return Promise.resolve(
        createJsonResponse({
          id: "run-1",
          status: "in_progress",
          stage: "build",
          output: null,
          error_message: null,
          branch: "main",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      );
    });

    mockStreamFetch.mockImplementation(() =>
      Promise.resolve(
        createSseResponse(
          'id: 1\ndata: {"type":"notification","timestamp":"2026-01-01T00:00:01Z","notification":{"jsonrpc":"2.0","method":"_posthog/console","params":{"sessionId":"run-1","level":"info","message":"hi"}}}\n\nevent: stream-end\ndata: {}\n\n',
        ),
      ),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    const hasWatcher = (): boolean =>
      (service as unknown as { watchers: Map<string, unknown> }).watchers.has(
        "task-1:run-1",
      );

    await waitFor(() => mockStreamFetch.mock.calls.length === 1);
    // Let the reconnect delay (2s base) elapse; with stream-end honored, none is scheduled.
    await vi.advanceTimersByTimeAsync(10_000);

    expect(mockStreamFetch.mock.calls.length).toBe(1);
    await waitFor(() => !hasWatcher());
  });

  it("emits the bootstrap snapshot when stream-end arrives mid-bootstrap", async () => {
    vi.useFakeTimers();

    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    const historicalEntry = {
      type: "notification",
      timestamp: "2026-01-01T00:00:01Z",
      notification: {
        jsonrpc: "2.0",
        method: "_posthog/console",
        params: { sessionId: "run-1", level: "info", message: "backlog" },
      },
    };

    // Hold the session_logs fetch open until the stream has already delivered
    // stream-end and closed, so completion races the bootstrap snapshot.
    let releaseSessionLogs: (() => void) | undefined;
    const sessionLogsGate = new Promise<void>((resolve) => {
      releaseSessionLogs = resolve;
    });

    mockNetFetch.mockImplementation(async (input: string | Request) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/session_logs/")) {
        await sessionLogsGate;
        return createJsonResponse([historicalEntry], 200, {
          "X-Has-More": "false",
        });
      }
      return createJsonResponse({
        id: "run-1",
        status: "in_progress",
        stage: "build",
        output: null,
        error_message: null,
        branch: "main",
        updated_at: "2026-01-01T00:00:00Z",
      });
    });

    mockStreamFetch.mockImplementation(() =>
      Promise.resolve(createSseResponse("event: stream-end\ndata: {}\n\n")),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    // Stream connects, delivers stream-end and EOFs while session_logs hangs.
    await waitFor(() => mockStreamFetch.mock.calls.length === 1);
    await vi.advanceTimersByTimeAsync(1_000);

    releaseSessionLogs?.();

    const hasWatcher = (): boolean =>
      (service as unknown as { watchers: Map<string, unknown> }).watchers.has(
        "task-1:run-1",
      );
    await waitFor(() => !hasWatcher());

    const snapshots = updates.filter(
      (u) =>
        typeof u === "object" &&
        u !== null &&
        (u as { kind?: string }).kind === "snapshot",
    );
    expect(snapshots).toHaveLength(1);
    expect(
      (snapshots[0] as { newEntries: unknown[] }).newEntries,
    ).toContainEqual(historicalEntry);
    // The stream-end stop must not schedule another connection.
    await vi.advanceTimersByTimeAsync(10_000);
    expect(mockStreamFetch.mock.calls.length).toBe(1);
  });

  it("repairs the final status when stream-end arrives without a terminal state event", async () => {
    vi.useFakeTimers();

    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    let runFetchCount = 0;
    mockNetFetch.mockImplementation((input: string | Request) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/session_logs/")) {
        return Promise.resolve(
          createJsonResponse([], 200, { "X-Has-More": "false" }),
        );
      }
      runFetchCount += 1;
      // First fetch bootstraps an active run; the stream then ends without ever
      // carrying a terminal task_run_state event, so the stop path must fetch
      // the completed status itself.
      return Promise.resolve(
        createJsonResponse(
          runFetchCount === 1
            ? {
                id: "run-1",
                status: "in_progress",
                stage: "build",
                output: null,
                error_message: null,
                branch: "main",
                updated_at: "2026-01-01T00:00:00Z",
              }
            : {
                id: "run-1",
                status: "completed",
                stage: null,
                output: { pr_url: "https://github.com/PostHog/code/pull/9" },
                error_message: null,
                branch: "main",
                updated_at: "2026-01-01T00:00:05Z",
              },
        ),
      );
    });

    mockStreamFetch.mockImplementation(() =>
      Promise.resolve(createSseResponse("event: stream-end\ndata: {}\n\n")),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    const hasWatcher = (): boolean =>
      (service as unknown as { watchers: Map<string, unknown> }).watchers.has(
        "task-1:run-1",
      );
    await waitFor(() => !hasWatcher());

    expect(updates).toContainEqual(
      expect.objectContaining({
        kind: "status",
        status: "completed",
        output: { pr_url: "https://github.com/PostHog/code/pull/9" },
      }),
    );
  });

  it("reads via the agent-proxy with a Bearer token when the server resolves a base url", async () => {
    vi.useFakeTimers();

    mockStreamTokenFetch.mockImplementation(() =>
      Promise.resolve(
        createJsonResponse({
          token: "proxy-token",
          stream_base_url: "https://proxy.example",
        }),
      ),
    );

    mockNetFetch.mockImplementation((input: string | Request) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/session_logs/")) {
        return Promise.resolve(
          createJsonResponse([], 200, { "X-Has-More": "false" }),
        );
      }
      return Promise.resolve(
        createJsonResponse({
          id: "run-1",
          status: "in_progress",
          stage: "build",
          output: null,
          error_message: null,
          branch: "main",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      );
    });

    mockStreamFetch.mockImplementation(() =>
      Promise.resolve(createSseResponse("event: stream-end\ndata: {}\n\n")),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(() => mockStreamFetch.mock.calls.length === 1);

    const [calledUrl, init] = mockStreamFetch.mock.calls[0];
    expect(String(calledUrl)).toMatch(
      /^https:\/\/proxy\.example\/v1\/runs\/run-1\/stream(\?|$)/,
    );
    expect((init?.headers as Record<string, string>)?.Authorization).toBe(
      "Bearer proxy-token",
    );
  });

  it("drops the resume position when the stream leg changes", async () => {
    vi.useFakeTimers();

    mockNetFetch.mockImplementation((input: string | Request) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/session_logs/")) {
        return Promise.resolve(
          createJsonResponse([], 200, { "X-Has-More": "false" }),
        );
      }
      return Promise.resolve(
        createJsonResponse({
          id: "run-1",
          status: "in_progress",
          stage: null,
          output: null,
          error_message: null,
          branch: "main",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      );
    });

    // First resolution fails transiently (connection falls back to Django and
    // records a Django-id-space resume position); the retried resolution routes
    // to the proxy, whose id space is unrelated.
    mockStreamTokenFetch
      .mockRejectedValueOnce(new Error("network blip"))
      .mockImplementation(() =>
        Promise.resolve(
          createJsonResponse({
            token: "proxy-token",
            stream_base_url: "https://proxy.example",
          }),
        ),
      );

    mockStreamFetch
      .mockImplementationOnce(() =>
        Promise.resolve(
          createSseResponse(
            'id: 7\nevent: keepalive\ndata: {"type":"keepalive"}\n\n',
          ),
        ),
      )
      .mockImplementation(() =>
        Promise.resolve(
          createOpenSseResponse(
            'event: keepalive\ndata: {"type":"keepalive"}\n\n',
          ),
        ),
      );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(() => mockStreamFetch.mock.calls.length >= 2, 10_000);

    const [firstUrl] = mockStreamFetch.mock.calls[0];
    const [secondUrl, secondInit] = mockStreamFetch.mock.calls[1];
    expect(String(firstUrl)).toContain("https://app.example.com/api/");
    expect(String(secondUrl)).toMatch(
      /^https:\/\/proxy\.example\/v1\/runs\/run-1\/stream/,
    );
    // The Django resume position must not leak into the proxy leg.
    expect(
      (secondInit?.headers as Record<string, string>)?.["Last-Event-ID"],
    ).toBeUndefined();
    expect(String(secondUrl)).toContain("start=latest");
  });

  it("old servers without stream_token use legacy polling to reconnect and stop", async () => {
    vi.useFakeTimers();

    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    // Old server: the endpoint does not exist, so no stream-end ever arrives and the
    // client must poll run status on each clean EOF to decide stop vs reconnect.
    mockStreamTokenFetch.mockImplementation(() =>
      Promise.resolve(createJsonResponse({ detail: "Not found" }, 404)),
    );

    let runFetchCount = 0;
    mockNetFetch.mockImplementation((input: string | Request) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/session_logs/")) {
        return Promise.resolve(
          createJsonResponse([], 200, { "X-Has-More": "false" }),
        );
      }
      runFetchCount += 1;
      // Calls 1-3 (bootstrap, post-bootstrap verify, first legacy poll) report an
      // active run; the second legacy poll reports terminal.
      const terminal = runFetchCount >= 4;
      return Promise.resolve(
        createJsonResponse({
          id: "run-1",
          status: terminal ? "completed" : "in_progress",
          stage: null,
          output: null,
          error_message: null,
          branch: "main",
          updated_at: terminal
            ? "2026-01-01T00:00:05Z"
            : "2026-01-01T00:00:00Z",
        }),
      );
    });

    // The flag-off server never emits stream-end; every connection just EOFs.
    mockStreamFetch.mockImplementation(() =>
      Promise.resolve(createSseResponse("")),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    const hasWatcher = (): boolean =>
      (service as unknown as { watchers: Map<string, unknown> }).watchers.has(
        "task-1:run-1",
      );
    await waitFor(() => !hasWatcher(), 10_000);

    // At least one legacy reconnect happened while the run was active, then the
    // terminal poll stopped the watcher; no further connections after that.
    const connectionsAtStop = mockStreamFetch.mock.calls.length;
    expect(connectionsAtStop).toBeGreaterThanOrEqual(2);
    expect(updates).toContainEqual(
      expect.objectContaining({ kind: "status", status: "completed" }),
    );
    await vi.advanceTimersByTimeAsync(10_000);
    expect(mockStreamFetch.mock.calls.length).toBe(connectionsAtStop);
    // The refused resolution is cached: one stream_token call for the whole watch.
    expect(mockStreamTokenFetch.mock.calls.length).toBe(1);
  });

  it("a transient stream_token failure retries resolution instead of pinning to Django", async () => {
    vi.useFakeTimers();

    // The endpoint is momentarily down (503): unlike a 404, this must not cache a Django fallback.
    // The next reconnect re-resolves and the watch upgrades to the durable proxy leg.
    mockStreamTokenFetch
      .mockImplementationOnce(() =>
        Promise.resolve(createJsonResponse({ detail: "unavailable" }, 503)),
      )
      .mockImplementation(() =>
        Promise.resolve(
          createJsonResponse({
            token: "fresh-token",
            stream_base_url: "https://proxy.example",
          }),
        ),
      );

    mockNetFetch.mockImplementation((input: string | Request) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/session_logs/")) {
        return Promise.resolve(
          createJsonResponse([], 200, { "X-Has-More": "false" }),
        );
      }
      return Promise.resolve(
        createJsonResponse({
          id: "run-1",
          status: "in_progress",
          stage: null,
          output: null,
          error_message: null,
          branch: "main",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      );
    });

    // Django leg (transient round) just EOFs to force a reconnect; once the proxy resolves it
    // emits stream-end so the watch completes, proving durable streaming engaged after the retry.
    const usedProxyLeg = (input: string | Request): boolean => {
      const url = typeof input === "string" ? input : input.url;
      return url.includes("proxy.example");
    };
    mockStreamFetch.mockImplementation((input: string | Request) =>
      Promise.resolve(
        usedProxyLeg(input)
          ? createSseResponse("event: stream-end\ndata: {}\n\n")
          : createSseResponse(""),
      ),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    const hasWatcher = (): boolean =>
      (service as unknown as { watchers: Map<string, unknown> }).watchers.has(
        "task-1:run-1",
      );
    await waitFor(() => !hasWatcher(), 10_000);

    // The 503 was not cached: resolution retried and the stream switched to the durable proxy leg.
    expect(mockStreamTokenFetch.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(
      mockStreamFetch.mock.calls.some(([input]) => usedProxyLeg(input)),
    ).toBe(true);
  });

  it("proxy 401 re-resolves the read target and resumes with a fresh token", async () => {
    vi.useFakeTimers();

    mockStreamTokenFetch
      .mockImplementationOnce(() =>
        Promise.resolve(
          createJsonResponse({
            token: "expired-token",
            stream_base_url: "https://proxy.example",
          }),
        ),
      )
      .mockImplementation(() =>
        Promise.resolve(
          createJsonResponse({
            token: "fresh-token",
            stream_base_url: "https://proxy.example",
          }),
        ),
      );

    mockNetFetch.mockImplementation((input: string | Request) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/session_logs/")) {
        return Promise.resolve(
          createJsonResponse([], 200, { "X-Has-More": "false" }),
        );
      }
      return Promise.resolve(
        createJsonResponse({
          id: "run-1",
          status: "in_progress",
          stage: null,
          output: null,
          error_message: null,
          branch: "main",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      );
    });

    mockStreamFetch
      .mockImplementationOnce(() =>
        Promise.resolve(createJsonResponse({ detail: "expired" }, 401)),
      )
      .mockImplementation(() =>
        Promise.resolve(
          createOpenSseResponse(
            'event: keepalive\ndata: {"type":"keepalive"}\n\n',
          ),
        ),
      );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(() => mockStreamFetch.mock.calls.length >= 2, 10_000);

    expect(mockStreamTokenFetch.mock.calls.length).toBe(2);
    const [secondUrl, secondInit] = mockStreamFetch.mock.calls[1];
    expect(String(secondUrl)).toMatch(
      /^https:\/\/proxy\.example\/v1\/runs\/run-1\/stream/,
    );
    expect((secondInit?.headers as Record<string, string>)?.Authorization).toBe(
      "Bearer fresh-token",
    );
    expect(
      (service as unknown as { watchers: Map<string, unknown> }).watchers.has(
        "task-1:run-1",
      ),
    ).toBe(true);
  });

  it("proxy 401 falls back to Django when the proxy is withdrawn", async () => {
    vi.useFakeTimers();

    // The re-resolution after the 401 no longer offers a proxy (rollout flag turned
    // off mid-run); the watcher continues on the Django leg, which still emits the
    // stream-end sentinel.
    mockStreamTokenFetch
      .mockImplementationOnce(() =>
        Promise.resolve(
          createJsonResponse({
            token: "expired-token",
            stream_base_url: "https://proxy.example",
          }),
        ),
      )
      .mockImplementation(() =>
        Promise.resolve(
          createJsonResponse({ token: "django-token", stream_base_url: null }),
        ),
      );

    let runFetchCount = 0;
    mockNetFetch.mockImplementation((input: string | Request) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/session_logs/")) {
        return Promise.resolve(
          createJsonResponse([], 200, { "X-Has-More": "false" }),
        );
      }
      runFetchCount += 1;
      const terminal = runFetchCount >= 2;
      return Promise.resolve(
        createJsonResponse({
          id: "run-1",
          status: terminal ? "completed" : "in_progress",
          stage: null,
          output: null,
          error_message: null,
          branch: "main",
          updated_at: terminal
            ? "2026-01-01T00:00:05Z"
            : "2026-01-01T00:00:00Z",
        }),
      );
    });

    mockStreamFetch
      .mockImplementationOnce(() =>
        Promise.resolve(createJsonResponse({ detail: "expired" }, 401)),
      )
      .mockImplementation(() =>
        Promise.resolve(createSseResponse("event: stream-end\ndata: {}\n\n")),
      );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    const hasWatcher = (): boolean =>
      (service as unknown as { watchers: Map<string, unknown> }).watchers.has(
        "task-1:run-1",
      );
    await waitFor(() => !hasWatcher(), 10_000);

    expect(mockStreamTokenFetch.mock.calls.length).toBe(2);
    const [secondUrl] = mockStreamFetch.mock.calls[1];
    expect(String(secondUrl)).toContain("https://app.example.com/api/");
  });

  it("stream-end still stops the watcher in legacy mode", async () => {
    vi.useFakeTimers();

    // Old server detected via 404, yet the stream delivers stream-end anyway (e.g. a
    // server upgraded mid-watch). The sentinel is honored in both modes.
    mockStreamTokenFetch.mockImplementation(() =>
      Promise.resolve(createJsonResponse({ detail: "Not found" }, 404)),
    );

    let runFetchCount = 0;
    mockNetFetch.mockImplementation((input: string | Request) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/session_logs/")) {
        return Promise.resolve(
          createJsonResponse([], 200, { "X-Has-More": "false" }),
        );
      }
      runFetchCount += 1;
      // Bootstrap sees an active run so the stream actually opens; the
      // stream-end stop path then repairs the status to terminal.
      const terminal = runFetchCount >= 2;
      return Promise.resolve(
        createJsonResponse({
          id: "run-1",
          status: terminal ? "completed" : "in_progress",
          stage: null,
          output: null,
          error_message: null,
          branch: "main",
          updated_at: terminal
            ? "2026-01-01T00:00:05Z"
            : "2026-01-01T00:00:00Z",
        }),
      );
    });

    mockStreamFetch.mockImplementation(() =>
      Promise.resolve(createSseResponse("event: stream-end\ndata: {}\n\n")),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    const hasWatcher = (): boolean =>
      (service as unknown as { watchers: Map<string, unknown> }).watchers.has(
        "task-1:run-1",
      );
    await waitFor(() => !hasWatcher(), 10_000);

    expect(mockStreamFetch.mock.calls.length).toBe(1);
  });

  it("re-bootstraps once on a clean-EOF loop and fails when it persists", async () => {
    vi.useFakeTimers();

    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    const makeInProgressRun = () =>
      createJsonResponse({
        id: "run-1",
        status: "in_progress",
        stage: null,
        output: null,
        error_message: null,
        branch: "main",
        updated_at: "2026-01-01T00:00:00Z",
      });

    mockNetFetch.mockImplementation((input: string | Request) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/session_logs/")) {
        return Promise.resolve(
          createJsonResponse([], 200, { "X-Has-More": "false" }),
        );
      }
      return Promise.resolve(makeInProgressRun());
    });

    mockStreamFetch.mockImplementation(() =>
      Promise.resolve(createSseResponse("")),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(() => mockStreamFetch.mock.calls.length === 1);
    await vi.advanceTimersByTimeAsync(60 * 60_000);

    await waitFor(
      () =>
        updates.some(
          (u) =>
            typeof u === "object" &&
            u !== null &&
            (u as { kind?: string }).kind === "error",
        ),
      10_000,
    );

    expect(updates).toContainEqual({
      taskId: "task-1",
      runId: "run-1",
      kind: "error",
      errorTitle: "Cloud run unreachable",
      errorMessage:
        "Could not maintain a connection to the cloud run after many attempts. Click retry once the issue is resolved.",
      retryable: true,
    });

    // The first budget exhaustion self-heals with a full rebuild (fresh read-leg
    // resolution and a second snapshot); only the second exhaustion fails.
    expect(
      updates.filter(
        (u) =>
          typeof u === "object" &&
          u !== null &&
          (u as { kind?: string }).kind === "snapshot",
      ),
    ).toHaveLength(2);
    expect(mockStreamTokenFetch.mock.calls.length).toBe(2);
  });

  it("retry rebuilds the watcher from scratch after a failure", async () => {
    vi.useFakeTimers();

    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    mockNetFetch.mockImplementation((input: string | Request) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/session_logs/")) {
        return Promise.resolve(
          createJsonResponse([], 200, { "X-Has-More": "false" }),
        );
      }
      return Promise.resolve(
        createJsonResponse({
          id: "run-1",
          status: "in_progress",
          stage: null,
          output: null,
          error_message: null,
          branch: "main",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      );
    });

    // Every connection records a resume position, then dies on a backend error
    // frame until the error budget fails the watcher.
    mockStreamFetch.mockImplementation(() =>
      Promise.resolve(
        createSseResponse(
          'id: 42\nevent: keepalive\ndata: {"type":"keepalive"}\n\nevent: error\ndata: {"error":"boom"}\n\n',
        ),
      ),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(() => mockStreamFetch.mock.calls.length === 1);
    await vi.advanceTimersByTimeAsync(70_000);
    await waitFor(
      () =>
        updates.some(
          (u) =>
            typeof u === "object" &&
            u !== null &&
            (u as { kind?: string }).kind === "error",
        ),
      10_000,
    );

    const countSnapshots = (): number =>
      updates.filter(
        (u) =>
          typeof u === "object" &&
          u !== null &&
          (u as { kind?: string }).kind === "snapshot",
      ).length;
    const tokenCallsBeforeRetry = mockStreamTokenFetch.mock.calls.length;
    const snapshotsBeforeRetry = countSnapshots();
    const streamCallsBeforeRetry = mockStreamFetch.mock.calls.length;

    mockStreamFetch.mockImplementation(() =>
      Promise.resolve(
        createOpenSseResponse(
          'event: keepalive\ndata: {"type":"keepalive"}\n\n',
        ),
      ),
    );

    service.retry("task-1", "run-1");

    await waitFor(
      () => mockStreamFetch.mock.calls.length === streamCallsBeforeRetry + 1,
    );
    await waitFor(() => countSnapshots() === snapshotsBeforeRetry + 1);

    // Retry must rebuild from server truth: re-resolve the read leg, re-emit a
    // fresh snapshot and drop the poisoned resume position instead of resuming
    // from the failed stream's Last-Event-ID.
    expect(mockStreamTokenFetch.mock.calls.length).toBe(
      tokenCallsBeforeRetry + 1,
    );
    const [, init] = mockStreamFetch.mock.calls[streamCallsBeforeRetry];
    expect(
      (init?.headers as Record<string, string>)?.["Last-Event-ID"],
    ).toBeUndefined();
  });

  it("emits a retryable cloud error after repeated stream failures", async () => {
    vi.useFakeTimers();

    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    const makeInProgressRun = () =>
      createJsonResponse({
        id: "run-1",
        status: "in_progress",
        stage: null,
        output: null,
        error_message: null,
        branch: "main",
        updated_at: "2026-01-01T00:00:00Z",
      });

    mockNetFetch
      .mockResolvedValueOnce(makeInProgressRun()) // bootstrap: fetchTaskRun
      .mockResolvedValueOnce(
        createJsonResponse([], 200, { "X-Has-More": "false" }),
      ) // bootstrap: fetchSessionLogs
      // Each stream error triggers handleStreamCompletion → fetchTaskRun
      .mockImplementation(() => Promise.resolve(makeInProgressRun()));

    mockStreamFetch.mockImplementation(() =>
      Promise.resolve(
        createSseResponse(
          'event: keepalive\ndata: {"type":"keepalive"}\n\nevent: error\ndata: {"error":"boom"}\n\n',
        ),
      ),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(() => mockStreamFetch.mock.calls.length === 1);
    await vi.advanceTimersByTimeAsync(70_000);
    await waitFor(
      () =>
        updates.some(
          (u) =>
            typeof u === "object" &&
            u !== null &&
            (u as { kind?: string }).kind === "error",
        ),
      10_000,
    );

    expect(mockStreamFetch.mock.calls.length).toBe(10);
    // Status is no longer polled per reconnect. Only the 2 bootstrap calls plus the single
    // post-bootstrap verification touch the status endpoint; reconnects never do.
    expect(mockNetFetch.mock.calls.length).toBeLessThanOrEqual(3);
    expect(updates).toContainEqual({
      taskId: "task-1",
      runId: "run-1",
      kind: "error",
      errorTitle: "Cloud stream disconnected",
      errorMessage:
        "Lost connection to the cloud run stream. Retry to reconnect.",
      retryable: true,
    });
  });

  it("clears the backend-error budget after a healthy long-lived cut", async () => {
    vi.useFakeTimers();

    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    const makeInProgressRun = () =>
      createJsonResponse({
        id: "run-1",
        status: "in_progress",
        stage: null,
        output: null,
        error_message: null,
        branch: "main",
        updated_at: "2026-01-01T00:00:00Z",
      });

    mockNetFetch
      .mockResolvedValueOnce(makeInProgressRun()) // bootstrap: fetchTaskRun
      .mockResolvedValueOnce(
        createJsonResponse([], 200, { "X-Has-More": "false" }),
      ) // bootstrap: fetchSessionLogs
      .mockImplementation(() => Promise.resolve(makeInProgressRun()));

    // First connection delivers an explicit backend error frame (accruing the
    // backend-error budget). Subsequent connections are healthy long-lived cuts
    // (>= SSE_HEALTHY_CONNECTION_MS): each proves the stream recovered and must
    // clear the backend-error budget, so it never accumulates for the run's life.
    let streamCall = 0;
    mockStreamFetch.mockImplementation(() => {
      streamCall += 1;
      if (streamCall === 1) {
        return Promise.resolve(
          createSseResponse('event: error\ndata: {"error":"boom"}\n\n'),
        );
      }
      const encoder = new TextEncoder();
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(
            encoder.encode('event: keepalive\ndata: {"type":"keepalive"}\n\n'),
          );
          setTimeout(() => controller.error(new Error("terminated")), 65_000);
        },
      });
      return Promise.resolve(
        new Response(stream, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      );
    });

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    const getWatcher = () =>
      (
        service as unknown as {
          watchers: Map<
            string,
            {
              reconnectAttempts: number;
              streamErrorAttempts: number;
              failed: boolean;
            }
          >;
        }
      ).watchers.get("task-1:run-1");

    // The backend error must have accrued the backend-error budget first...
    await waitFor(() => (getWatcher()?.streamErrorAttempts ?? 0) >= 1, 20_000);
    // ...then the healthy long-lived cut on the next connection clears it.
    await vi.advanceTimersByTimeAsync(67_000 * 2);
    await waitFor(() => getWatcher()?.streamErrorAttempts === 0, 20_000);

    const watcher = getWatcher();
    expect(watcher?.failed).toBe(false);
    expect(watcher?.streamErrorAttempts).toBe(0);
    expect(watcher?.reconnectAttempts).toBe(0);
    expect(
      updates.some(
        (u) =>
          typeof u === "object" &&
          u !== null &&
          (u as { kind?: string }).kind === "error",
      ),
    ).toBe(false);
  });

  it("counts quick stream failures and surfaces a retryable error", async () => {
    vi.useFakeTimers();

    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    const makeInProgressRun = () =>
      createJsonResponse({
        id: "run-1",
        status: "in_progress",
        stage: null,
        output: null,
        error_message: null,
        branch: "main",
        updated_at: "2026-01-01T00:00:00Z",
      });

    mockNetFetch
      .mockResolvedValueOnce(makeInProgressRun())
      .mockResolvedValueOnce(
        createJsonResponse([], 200, { "X-Has-More": "false" }),
      )
      .mockImplementation(() => Promise.resolve(makeInProgressRun()));

    // Connections that fail immediately (under SSE_HEALTHY_CONNECTION_MS) are
    // genuine churn and must keep counting toward the retry budget.
    mockStreamFetch.mockImplementation(() =>
      Promise.resolve(
        createSseResponse('event: error\ndata: {"error":"boom"}\n\n'),
      ),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(() => mockStreamFetch.mock.calls.length === 1);
    await vi.advanceTimersByTimeAsync(70_000);
    await waitFor(
      () =>
        updates.some(
          (u) =>
            typeof u === "object" &&
            u !== null &&
            (u as { kind?: string }).kind === "error",
        ),
      10_000,
    );

    expect(updates).toContainEqual({
      taskId: "task-1",
      runId: "run-1",
      kind: "error",
      errorTitle: "Cloud stream disconnected",
      errorMessage:
        "Lost connection to the cloud run stream. Retry to reconnect.",
      retryable: true,
    });
  });

  it("reconnects on a clean EOF even after the run status goes terminal (status-unaware)", async () => {
    vi.useFakeTimers();

    // Bootstrap sees an active run (so it streams); every later status fetch reports terminal.
    // Pre-decoupling, a clean EOF on a terminal run stopped the watch. Now run status is never
    // consulted to decide reconnects, so the clean EOFs keep reconnecting until stream-end.
    let statusFetchCount = 0;
    mockNetFetch.mockImplementation((input: string | Request) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/session_logs/")) {
        return Promise.resolve(
          createJsonResponse([], 200, { "X-Has-More": "false" }),
        );
      }
      statusFetchCount += 1;
      return Promise.resolve(
        createJsonResponse({
          id: "run-1",
          status: statusFetchCount === 1 ? "in_progress" : "completed",
          stage: null,
          output: null,
          error_message: null,
          branch: "main",
          updated_at:
            statusFetchCount === 1
              ? "2026-01-01T00:00:00Z"
              : "2026-01-01T00:00:01Z",
        }),
      );
    });

    mockStreamFetch.mockImplementation(() =>
      Promise.resolve(createSseResponse("")),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(() => mockStreamFetch.mock.calls.length === 1);
    await waitFor(() => mockStreamFetch.mock.calls.length >= 3, 20_000);

    // Terminal status did not stop the watch; the watcher is still reconnecting.
    expect(
      (service as unknown as { watchers: Map<string, unknown> }).watchers.has(
        "task-1:run-1",
      ),
    ).toBe(true);
  });

  it("surfaces a retryable error when the backend errors even on a long-lived stream", async () => {
    vi.useFakeTimers();

    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    const makeInProgressRun = () =>
      createJsonResponse({
        id: "run-1",
        status: "in_progress",
        stage: null,
        output: null,
        error_message: null,
        branch: "main",
        updated_at: "2026-01-01T00:00:00Z",
      });

    mockNetFetch
      .mockResolvedValueOnce(makeInProgressRun())
      .mockResolvedValueOnce(
        createJsonResponse([], 200, { "X-Has-More": "false" }),
      )
      .mockImplementation(() => Promise.resolve(makeInProgressRun()));

    // Each connection stays open with a keepalive for 65s (> the healthy
    // threshold) and only THEN emits an explicit backend `event: error` frame.
    // An explicit backend error must always count toward the budget, so even a
    // long-lived stream eventually surfaces the retryable disconnect error.
    mockStreamFetch.mockImplementation(() => {
      const encoder = new TextEncoder();
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(
            encoder.encode('event: keepalive\ndata: {"type":"keepalive"}\n\n'),
          );
          setTimeout(() => {
            controller.enqueue(
              encoder.encode('event: error\ndata: {"error":"boom"}\n\n'),
            );
            controller.close();
          }, 65_000);
        },
      });
      return Promise.resolve(
        new Response(stream, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      );
    });

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(() => mockStreamFetch.mock.calls.length === 1);
    // Drive >= 10 long-lived-then-backend-error cycles (65s open + backoff each).
    await vi.advanceTimersByTimeAsync(65_000 * 11 + 70_000);
    await waitFor(
      () =>
        updates.some(
          (u) =>
            typeof u === "object" &&
            u !== null &&
            (u as { kind?: string }).kind === "error",
        ),
      10_000,
    );

    expect(updates).toContainEqual({
      taskId: "task-1",
      runId: "run-1",
      kind: "error",
      errorTitle: "Cloud stream disconnected",
      errorMessage:
        "Lost connection to the cloud run stream. Retry to reconnect.",
      retryable: true,
    });
  });

  it("treats a long-lived transport cut as healthy even with no frames received", async () => {
    vi.useFakeTimers();

    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    const makeInProgressRun = () =>
      createJsonResponse({
        id: "run-1",
        status: "in_progress",
        stage: null,
        output: null,
        error_message: null,
        branch: "main",
        updated_at: "2026-01-01T00:00:00Z",
      });

    mockNetFetch
      .mockResolvedValueOnce(makeInProgressRun())
      .mockResolvedValueOnce(
        createJsonResponse([], 200, { "X-Has-More": "false" }),
      )
      .mockImplementation(() => Promise.resolve(makeInProgressRun()));

    // Each connection opens, delivers nothing, then is transport-cut at 65s. Healthiness is
    // duration-only (not keepalive frames), so even a frame-less long-lived cut never exhausts the budget.
    mockStreamFetch.mockImplementation(() => {
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          setTimeout(() => controller.error(new Error("terminated")), 65_000);
        },
      });
      return Promise.resolve(
        new Response(stream, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      );
    });

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(() => mockStreamFetch.mock.calls.length === 1);
    await vi.advanceTimersByTimeAsync(67_000 * 8);
    await waitFor(() => mockStreamFetch.mock.calls.length >= 6, 20_000);

    expect(
      updates.some(
        (u) =>
          typeof u === "object" &&
          u !== null &&
          (u as { kind?: string }).kind === "error",
      ),
    ).toBe(false);

    const watcher = (
      service as unknown as {
        watchers: Map<string, { reconnectAttempts: number; failed: boolean }>;
      }
    ).watchers.get("task-1:run-1");
    expect(watcher?.failed).toBe(false);
    expect(watcher?.reconnectAttempts).toBe(0);
  });

  it("never fails an idle run riding healthy clean-EOF reconnect cycles", async () => {
    vi.useFakeTimers();

    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    mockNetFetch.mockImplementation((input: string | Request) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/session_logs/")) {
        return Promise.resolve(
          createJsonResponse([], 200, { "X-Has-More": "false" }),
        );
      }
      return Promise.resolve(
        createJsonResponse({
          id: "run-1",
          status: "in_progress",
          stage: null,
          output: null,
          error_message: null,
          branch: "main",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      );
    });

    // An idle run: every connection delivers only a keepalive, lives a healthy
    // 65s, then the server closes it cleanly. No data events ever arrive, so
    // nothing else resets the cumulative budget across the cycles.
    mockStreamFetch.mockImplementation(() => {
      const encoder = new TextEncoder();
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(
            encoder.encode('event: keepalive\ndata: {"type":"keepalive"}\n\n'),
          );
          setTimeout(() => controller.close(), 65_000);
        },
      });
      return Promise.resolve(
        new Response(stream, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      );
    });

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(() => mockStreamFetch.mock.calls.length === 1);
    // Ride out more cycles than the cumulative budget allows for loops.
    await vi.advanceTimersByTimeAsync(67_000 * 35);
    await waitFor(() => mockStreamFetch.mock.calls.length >= 32, 20_000);

    expect(
      updates.some(
        (u) =>
          typeof u === "object" &&
          u !== null &&
          (u as { kind?: string }).kind === "error",
      ),
    ).toBe(false);
    expect(
      (service as unknown as { watchers: Map<string, unknown> }).watchers.has(
        "task-1:run-1",
      ),
    ).toBe(true);
  });

  it("resets the transport reconnect budget once a keepalive proves recovery", async () => {
    vi.useFakeTimers();

    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    const makeInProgressRun = () =>
      createJsonResponse({
        id: "run-1",
        status: "in_progress",
        stage: null,
        output: null,
        error_message: null,
        branch: "main",
        updated_at: "2026-01-01T00:00:00Z",
      });

    mockNetFetch
      .mockResolvedValueOnce(makeInProgressRun())
      .mockResolvedValueOnce(
        createJsonResponse([], 200, { "X-Has-More": "false" }),
      )
      .mockImplementation(() => Promise.resolve(makeInProgressRun()));

    // First 3 connections fail fast at the transport level and accrue reconnect attempts. The 4th
    // delivers a keepalive and stays open, proving recovery, so the accrued attempts must reset.
    let streamCall = 0;
    const keepaliveControllerRef: {
      current: ReadableStreamDefaultController<Uint8Array> | null;
    } = { current: null };
    const encoder = new TextEncoder();
    mockStreamFetch.mockImplementation(() => {
      streamCall += 1;
      if (streamCall <= 3) {
        const stream = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.error(new Error("terminated"));
          },
        });
        return Promise.resolve(
          new Response(stream, {
            status: 200,
            headers: { "Content-Type": "text/event-stream" },
          }),
        );
      }
      // 4th connection stays open with no frame; the test injects the keepalive
      // below so it can observe the accrued budget BEFORE the reset.
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          keepaliveControllerRef.current = controller;
        },
      });
      return Promise.resolve(
        new Response(stream, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      );
    });

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    const getWatcher = () =>
      (
        service as unknown as {
          watchers: Map<string, { reconnectAttempts: number; failed: boolean }>;
        }
      ).watchers.get("task-1:run-1");

    await waitFor(() => mockStreamFetch.mock.calls.length === 1);
    // Drive the 3 fast transport failures and open the held 4th connection.
    await vi.advanceTimersByTimeAsync(30_000);
    await waitFor(
      () => streamCall >= 4 && !!keepaliveControllerRef.current,
      20_000,
    );

    // Non-vacuous precondition: the fast failures actually accrued the budget.
    expect(getWatcher()?.reconnectAttempts ?? 0).toBeGreaterThan(0);

    // A keepalive on the recovered connection must reset the transport budget.
    keepaliveControllerRef.current?.enqueue(
      encoder.encode('event: keepalive\ndata: {"type":"keepalive"}\n\n'),
    );
    await waitFor(() => getWatcher()?.reconnectAttempts === 0, 20_000);

    const watcher = getWatcher();
    expect(watcher?.failed).toBe(false);
    expect(watcher?.reconnectAttempts).toBe(0);
    expect(
      updates.some(
        (u) =>
          typeof u === "object" &&
          u !== null &&
          (u as { kind?: string }).kind === "error",
      ),
    ).toBe(false);
  });

  it("stops a cloud run through the run cancel endpoint", async () => {
    mockNetFetch.mockResolvedValueOnce(
      createJsonResponse({ id: "run-1", status: "in_progress" }, 202),
    );

    const result = await service.stop({
      taskId: "task-1",
      runId: "run-1",
    });

    expect(result).toEqual({ success: true, runStatus: "in_progress" });
    const [url, init] = mockNetFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "https://us.posthog.com/api/projects/2/tasks/task-1/runs/run-1/cancel/",
    );
    expect(init.method).toBe("POST");
  });

  it("surfaces the backend error and retryability when a stop fails", async () => {
    mockNetFetch.mockResolvedValueOnce(
      createJsonResponse(
        { error: "Could not reach the run's workflow; try again" },
        503,
      ),
    );

    const result = await service.stop({
      taskId: "task-1",
      runId: "run-1",
    });

    expect(result.success).toBe(false);
    expect(result.error).toBe("Could not reach the run's workflow; try again");
    expect(result.retryable).toBe(true);
  });

  it("does not let a stale backend-error count inflate a transport reconnect delay", async () => {
    vi.useFakeTimers();

    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    const makeInProgressRun = () =>
      createJsonResponse({
        id: "run-1",
        status: "in_progress",
        stage: null,
        output: null,
        error_message: null,
        branch: "main",
        updated_at: "2026-01-01T00:00:00Z",
      });

    mockNetFetch
      .mockResolvedValueOnce(makeInProgressRun()) // bootstrap: fetchTaskRun
      .mockResolvedValueOnce(
        createJsonResponse([], 200, { "X-Has-More": "false" }),
      ) // bootstrap: fetchSessionLogs
      .mockImplementation(() => Promise.resolve(makeInProgressRun()));

    // Connections 1-4 each emit a backend error frame, pacing reconnects on streamErrorAttempts.
    // Connection 5 is held open until a quick transport cut, which must pace on the transport budget
    // (1 -> ~2s), not the stale backend-error budget (4 -> ~16s). Math.max(both) would use the latter.
    let streamCall = 0;
    const transportControllerRef: {
      current: ReadableStreamDefaultController<Uint8Array> | null;
    } = { current: null };
    mockStreamFetch.mockImplementation(() => {
      streamCall += 1;
      if (streamCall <= 4) {
        return Promise.resolve(
          createSseResponse('event: error\ndata: {"error":"boom"}\n\n'),
        );
      }
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          if (streamCall === 5) {
            transportControllerRef.current = controller;
          }
        },
      });
      return Promise.resolve(
        new Response(stream, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      );
    });

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    const getWatcher = () =>
      (
        service as unknown as {
          watchers: Map<
            string,
            {
              reconnectAttempts: number;
              streamErrorAttempts: number;
              failed: boolean;
            }
          >;
        }
      ).watchers.get("task-1:run-1");

    await waitFor(() => mockStreamFetch.mock.calls.length === 1);
    // Drive the four backend-error reconnects (2s + 4s + 8s + 16s of backoff)
    // and open the held fifth connection.
    await vi.advanceTimersByTimeAsync(35_000);
    await waitFor(
      () => streamCall >= 5 && !!transportControllerRef.current,
      20_000,
    );

    // Non-vacuous precondition: the backend-error budget is stale-high while the
    // transport budget is still zero.
    expect(getWatcher()?.streamErrorAttempts).toBe(4);
    expect(getWatcher()?.reconnectAttempts).toBe(0);
    expect(getWatcher()?.failed).toBe(false);

    // A quick transport cut on the open fifth connection charges ONE transport
    // attempt; its reconnect must wait ~2s (transport budget), not ~16s.
    transportControllerRef.current?.error(new Error("terminated"));
    await waitFor(() => getWatcher()?.reconnectAttempts === 1, 20_000);
    expect(getWatcher()?.streamErrorAttempts).toBe(4);

    const callsBeforeProbe = mockStreamFetch.mock.calls.length;
    // 5s is past the fixed ~2s transport backoff but well short of the buggy
    // ~16s backend-error backoff, so the sixth connection only opens if the
    // delay was paced on the transport budget.
    await vi.advanceTimersByTimeAsync(5_000);
    expect(mockStreamFetch.mock.calls.length).toBe(callsBeforeProbe + 1);
    expect(getWatcher()?.failed).toBe(false);
  });

  it("does not poll run status per reconnect on clean EOFs (status-unaware)", async () => {
    vi.useFakeTimers();

    let statusFetchCount = 0;
    mockNetFetch.mockImplementation((input: string | Request) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/session_logs/")) {
        return Promise.resolve(
          createJsonResponse([], 200, { "X-Has-More": "false" }),
        );
      }
      statusFetchCount += 1;
      return Promise.resolve(
        createJsonResponse({
          id: "run-1",
          status: "in_progress",
          stage: null,
          output: null,
          error_message: null,
          branch: "main",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      );
    });

    // Every connection ends cleanly with no stream-end sentinel, forcing reconnect after reconnect.
    mockStreamFetch.mockImplementation(() =>
      Promise.resolve(createSseResponse("")),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(() => mockStreamFetch.mock.calls.length >= 5, 20_000);

    // Bootstrap fetches status once and the post-bootstrap verification once more; reconnects add
    // none. Pre-decoupling, every clean EOF polled status, so this count would climb with reconnects.
    expect(statusFetchCount).toBeLessThanOrEqual(2);
  });

  const guardedFetchStatusExpectations = [
    [
      401,
      {
        errorTitle: "Cloud authentication expired",
        errorMessage: "Please reauthenticate and retry the cloud run stream.",
        retryable: true,
      },
    ],
    [
      403,
      {
        errorTitle: "Cloud access denied",
        errorMessage:
          "You no longer have access to this cloud run. Reauthenticate and retry.",
        retryable: true,
      },
    ],
    [
      404,
      {
        errorTitle: "Cloud run not found",
        errorMessage:
          "This cloud run could not be found. It may have been deleted or moved.",
        retryable: false,
      },
    ],
  ] as const;

  const guardedFetchStatusCases = (
    ["status fetch", "persisted log fetch"] as const
  ).flatMap((fetchPhase) =>
    guardedFetchStatusExpectations.map(([status, expectedError]) => ({
      fetchPhase,
      status,
      expectedError,
    })),
  );

  it.each(guardedFetchStatusCases)(
    "fails the watcher when $fetchPhase returns $status",
    async ({ fetchPhase, status, expectedError }) => {
      const updates: unknown[] = [];
      service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

      if (fetchPhase === "status fetch") {
        mockNetFetch.mockResolvedValueOnce(
          createJsonResponse({ detail: "Access denied" }, status),
        );
      } else {
        mockNetFetch
          .mockResolvedValueOnce(
            createJsonResponse({
              id: "run-1",
              status: "completed",
              stage: null,
              output: null,
              error_message: null,
              branch: "main",
              updated_at: "2026-01-01T00:00:00Z",
              completed_at: "2026-01-01T00:00:01Z",
            }),
          )
          .mockResolvedValueOnce(
            createJsonResponse({ detail: "Access denied" }, status),
          );
      }

      service.watch({
        taskId: "task-1",
        runId: "run-1",
        apiHost: "https://app.example.com",
        teamId: 2,
      });

      await waitFor(() => updates.length === 1);

      expect(mockStreamFetch).not.toHaveBeenCalled();
      expect(updates).toContainEqual({
        taskId: "task-1",
        runId: "run-1",
        kind: "error",
        ...expectedError,
      });
    },
  );

  it("loads paginated persisted logs once for an already terminal run", async () => {
    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    mockNetFetch
      .mockResolvedValueOnce(
        createJsonResponse({
          id: "run-1",
          status: "completed",
          stage: "build",
          output: null,
          error_message: null,
          branch: "main",
          updated_at: "2026-01-01T00:00:00Z",
          completed_at: "2026-01-01T00:00:00Z",
        }),
      )
      .mockResolvedValueOnce(
        createJsonResponse(
          [
            {
              type: "notification",
              timestamp: "2026-01-01T00:00:01Z",
              notification: {
                jsonrpc: "2.0",
                method: "_posthog/console",
                params: {
                  sessionId: "run-1",
                  level: "info",
                  message: "done-1",
                },
              },
            },
          ],
          200,
          { "X-Has-More": "true" },
        ),
      )
      .mockResolvedValueOnce(
        createJsonResponse(
          [
            {
              type: "notification",
              timestamp: "2026-01-01T00:00:02Z",
              notification: {
                jsonrpc: "2.0",
                method: "_posthog/console",
                params: {
                  sessionId: "run-1",
                  level: "info",
                  message: "done-2",
                },
              },
            },
          ],
          200,
          { "X-Has-More": "false" },
        ),
      );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(() => updates.length >= 1);

    expect(updates).toEqual([
      {
        taskId: "task-1",
        runId: "run-1",
        kind: "snapshot",
        newEntries: [
          {
            type: "notification",
            timestamp: "2026-01-01T00:00:01Z",
            notification: {
              jsonrpc: "2.0",
              method: "_posthog/console",
              params: {
                sessionId: "run-1",
                level: "info",
                message: "done-1",
              },
            },
          },
          {
            type: "notification",
            timestamp: "2026-01-01T00:00:02Z",
            notification: {
              jsonrpc: "2.0",
              method: "_posthog/console",
              params: {
                sessionId: "run-1",
                level: "info",
                message: "done-2",
              },
            },
          },
        ],
        totalEntryCount: 2,
        status: "completed",
        stage: "build",
        output: null,
        errorMessage: null,
        branch: "main",
      },
    ]);
    expect(mockNetFetch).toHaveBeenCalledTimes(3);
  });

  it("fails a Django-leg watcher on a stream 401 without re-resolving the read target", async () => {
    vi.useFakeTimers();

    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    // Default stream_token resolves with stream_base_url: null, so the read leg is Django.
    mockNetFetch.mockImplementation((input: string | Request) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/session_logs/")) {
        return Promise.resolve(
          createJsonResponse([], 200, { "X-Has-More": "false" }),
        );
      }
      return Promise.resolve(
        createJsonResponse({
          id: "run-1",
          status: "in_progress",
          stage: null,
          output: null,
          error_message: null,
          branch: "main",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      );
    });

    // A Django-leg 401 is fatal (autoRetry: false). The proxy re-resolve path is guarded on a
    // non-null streamBaseUrl, so a Django leg must fail rather than re-mint a stream_token.
    mockStreamFetch.mockImplementation(() =>
      Promise.resolve(createJsonResponse({ detail: "expired" }, 401)),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(
      () =>
        updates.some(
          (u) =>
            typeof u === "object" &&
            u !== null &&
            (u as { kind?: string }).kind === "error",
        ),
      10_000,
    );

    expect(updates).toContainEqual({
      taskId: "task-1",
      runId: "run-1",
      kind: "error",
      errorTitle: "Cloud authentication expired",
      errorMessage: "Please reauthenticate and retry the cloud run stream.",
      retryable: true,
    });

    // The Django leg did not re-resolve, and the fatal failure schedules no reconnect.
    expect(mockStreamTokenFetch.mock.calls.length).toBe(1);
    const streamCallsAtFailure = mockStreamFetch.mock.calls.length;
    await vi.advanceTimersByTimeAsync(10_000);
    expect(mockStreamFetch.mock.calls.length).toBe(streamCallsAtFailure);
    expect(mockStreamTokenFetch.mock.calls.length).toBe(1);
  });

  it("treats a 429 from stream_token as transient and retries the read-target resolution", async () => {
    vi.useFakeTimers();

    // 429 is momentary like a 503: it must not cache a Django fallback. The next reconnect
    // re-resolves and the watch upgrades to the durable proxy leg.
    mockStreamTokenFetch
      .mockImplementationOnce(() =>
        Promise.resolve(createJsonResponse({ detail: "slow down" }, 429)),
      )
      .mockImplementation(() =>
        Promise.resolve(
          createJsonResponse({
            token: "fresh-token",
            stream_base_url: "https://proxy.example",
          }),
        ),
      );

    mockNetFetch.mockImplementation((input: string | Request) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/session_logs/")) {
        return Promise.resolve(
          createJsonResponse([], 200, { "X-Has-More": "false" }),
        );
      }
      return Promise.resolve(
        createJsonResponse({
          id: "run-1",
          status: "in_progress",
          stage: null,
          output: null,
          error_message: null,
          branch: "main",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      );
    });

    const usedProxyLeg = (input: string | Request): boolean => {
      const url = typeof input === "string" ? input : input.url;
      return url.includes("proxy.example");
    };
    mockStreamFetch.mockImplementation((input: string | Request) =>
      Promise.resolve(
        usedProxyLeg(input)
          ? createSseResponse("event: stream-end\ndata: {}\n\n")
          : createSseResponse(""),
      ),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    const hasWatcher = (): boolean =>
      (service as unknown as { watchers: Map<string, unknown> }).watchers.has(
        "task-1:run-1",
      );
    await waitFor(() => !hasWatcher(), 10_000);

    // The 429 was not cached: resolution retried and the stream switched to the durable proxy leg.
    expect(mockStreamTokenFetch.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(
      mockStreamFetch.mock.calls.some(([input]) => usedProxyLeg(input)),
    ).toBe(true);
  });

  it("caches a 403 from stream_token and falls back to Django legacy polling", async () => {
    vi.useFakeTimers();

    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    // 403 is not transient: like a 404 it pins the watch to the Django leg with status polling.
    mockStreamTokenFetch.mockImplementation(() =>
      Promise.resolve(createJsonResponse({ detail: "forbidden" }, 403)),
    );

    let runFetchCount = 0;
    mockNetFetch.mockImplementation((input: string | Request) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/session_logs/")) {
        return Promise.resolve(
          createJsonResponse([], 200, { "X-Has-More": "false" }),
        );
      }
      runFetchCount += 1;
      // Calls 1-3 (bootstrap, post-bootstrap verify, first legacy poll) report an active run; the
      // second legacy poll reports terminal.
      const terminal = runFetchCount >= 4;
      return Promise.resolve(
        createJsonResponse({
          id: "run-1",
          status: terminal ? "completed" : "in_progress",
          stage: null,
          output: null,
          error_message: null,
          branch: "main",
          updated_at: terminal
            ? "2026-01-01T00:00:05Z"
            : "2026-01-01T00:00:00Z",
        }),
      );
    });

    // Legacy mode: no stream-end ever arrives, so each clean EOF triggers a status poll.
    mockStreamFetch.mockImplementation(() =>
      Promise.resolve(createSseResponse("")),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    const hasWatcher = (): boolean =>
      (service as unknown as { watchers: Map<string, unknown> }).watchers.has(
        "task-1:run-1",
      );
    await waitFor(() => !hasWatcher(), 10_000);

    // Every stream read used the Django leg (no proxy URL), the watcher stopped on the terminal
    // poll, and the refused resolution was cached: one stream_token call for the whole watch.
    expect(
      mockStreamFetch.mock.calls.every(([input]) => {
        const url = typeof input === "string" ? input : (input as Request).url;
        const { origin, pathname } = new URL(url);
        return (
          origin === "https://app.example.com" && pathname.startsWith("/api/")
        );
      }),
    ).toBe(true);
    expect(updates).toContainEqual(
      expect.objectContaining({ kind: "status", status: "completed" }),
    );
    expect(mockStreamTokenFetch.mock.calls.length).toBe(1);
  });

  it("stops on the last-known status when the post-stream-end repair fetch fails", async () => {
    vi.useFakeTimers();

    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    let runFetchCount = 0;
    mockNetFetch.mockImplementation((input: string | Request) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/session_logs/")) {
        return Promise.resolve(
          createJsonResponse([], 200, { "X-Has-More": "false" }),
        );
      }
      runFetchCount += 1;
      // Bootstrap (call 1) reports an active run so the stream opens; the stream-end stop path's
      // status-repair fetch (call 2) fails the network instead of returning a terminal run.
      if (runFetchCount >= 2) {
        return Promise.reject(new Error("network down"));
      }
      return Promise.resolve(
        createJsonResponse({
          id: "run-1",
          status: "in_progress",
          stage: "build",
          output: null,
          error_message: null,
          branch: "main",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      );
    });

    mockStreamFetch.mockImplementation(() =>
      Promise.resolve(createSseResponse("event: stream-end\ndata: {}\n\n")),
    );

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    const hasWatcher = (): boolean =>
      (service as unknown as { watchers: Map<string, unknown> }).watchers.has(
        "task-1:run-1",
      );
    await waitFor(() => !hasWatcher(), 10_000);

    // The failed repair fetch must not strand the watcher; it stops on the last-known status.
    expect(updates).toContainEqual(
      expect.objectContaining({ kind: "status", status: "in_progress" }),
    );
    // Exactly one stream connection (the bootstrap stream-end); no reconnect after the clean stop.
    expect(mockStreamFetch.mock.calls.length).toBe(1);
  });

  it("re-arms self-heal after a data event and re-bootstraps a second time before failing", async () => {
    vi.useFakeTimers();

    const updates: unknown[] = [];
    service.on(CloudTaskEvent.Update, (payload) => updates.push(payload));

    mockNetFetch.mockImplementation((input: string | Request) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/session_logs/")) {
        return Promise.resolve(
          createJsonResponse([], 200, { "X-Has-More": "false" }),
        );
      }
      return Promise.resolve(
        createJsonResponse({
          id: "run-1",
          status: "in_progress",
          stage: null,
          output: null,
          error_message: null,
          branch: "main",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      );
    });

    // Clean-EOF loop by default. Each re-bootstrap re-resolves the read target, so a second
    // stream_token call marks the first self-heal. Deliver exactly one real data event on that
    // re-bootstrap's connection to re-arm self-heal, then resume clean-EOF looping.
    let dataEventDelivered = false;
    mockStreamFetch.mockImplementation(() => {
      if (mockStreamTokenFetch.mock.calls.length >= 2 && !dataEventDelivered) {
        dataEventDelivered = true;
        return Promise.resolve(
          createSseResponse(
            'id: 1\ndata: {"type":"notification","timestamp":"2026-01-01T00:00:02Z","notification":{"jsonrpc":"2.0","method":"_posthog/console","params":{"sessionId":"run-1","level":"info","message":"alive"}}}\n\n',
          ),
        );
      }
      return Promise.resolve(createSseResponse(""));
    });

    service.watch({
      taskId: "task-1",
      runId: "run-1",
      apiHost: "https://app.example.com",
      teamId: 2,
    });

    await waitFor(() => mockStreamFetch.mock.calls.length === 1);
    await vi.advanceTimersByTimeAsync(2 * 60 * 60_000);

    await waitFor(
      () =>
        updates.some(
          (u) =>
            typeof u === "object" &&
            u !== null &&
            (u as { kind?: string }).kind === "error",
        ),
      10_000,
    );

    expect(updates).toContainEqual(
      expect.objectContaining({
        kind: "error",
        errorTitle: "Cloud run unreachable",
      }),
    );

    // Initial bootstrap snapshot plus two self-heal re-bootstraps: the data event between the first
    // and second budget exhaustion re-armed self-heal, so a third snapshot precedes the failure.
    expect(
      updates.filter(
        (u) =>
          typeof u === "object" &&
          u !== null &&
          (u as { kind?: string }).kind === "snapshot",
      ),
    ).toHaveLength(3);
  });
});

describe("CloudTaskService MCP relay", () => {
  let relayService: CloudTaskService;
  let mcpRelayExecutor: {
    execute: ReturnType<typeof vi.fn>;
    closeRun: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    const scopedLog = {
      debug: vi.fn(),
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
    };
    const loggerMock = { ...scopedLog, scope: vi.fn(() => scopedLog) };
    const analyticsMock = { track: vi.fn() };
    mcpRelayExecutor = {
      execute: vi.fn(async () => ({
        payload: { jsonrpc: "2.0", id: 1, result: {} },
      })),
      closeRun: vi.fn(async () => {}),
    };
    relayService = new CloudTaskService(
      mockAuthService as never,
      analyticsMock as never,
      loggerMock,
      mcpRelayExecutor as never,
    );

    mockNetFetch.mockReset();
    mockStreamFetch.mockReset();
    mockStreamTokenFetch.mockReset();
    mockStreamTokenFetch.mockImplementation(() =>
      Promise.resolve(
        createJsonResponse({ token: "test-token", stream_base_url: null }),
      ),
    );
    mockAuthService.authenticatedFetch.mockReset();
    vi.stubGlobal("fetch", fetchRouter);
    mockAuthService.authenticatedFetch.mockImplementation(
      async (input: string | Request, init?: RequestInit) => {
        return fetchRouter(input, {
          ...init,
          headers: {
            ...(init?.headers ?? {}),
            Authorization: "Bearer token",
          },
        });
      },
    );
  });

  afterEach(() => {
    relayService.unwatchAll();
    vi.unstubAllGlobals();
  });

  function mcpRequestSseLine(
    overrides: Partial<{
      requestId: string;
      server: string;
      expiresAt: string;
      payload: Record<string, unknown>;
    }> = {},
  ): string {
    const event = {
      type: "mcp_request",
      requestId: overrides.requestId ?? "req-1",
      server: overrides.server ?? "slack",
      payload: overrides.payload ?? {
        jsonrpc: "2.0",
        id: 1,
        method: "initialize",
      },
      expiresAt:
        overrides.expiresAt ?? new Date(Date.now() + 60_000).toISOString(),
    };
    return `data: ${JSON.stringify(event)}\n\n`;
  }

  function toolsCallPayload(
    args: Record<string, unknown> = { channel: "#general" },
  ): Record<string, unknown> {
    return {
      jsonrpc: "2.0",
      id: 2,
      method: "tools/call",
      params: { name: "send_message", arguments: args },
    };
  }

  function createControllableSseResponse(): {
    response: Response;
    push: (chunk: string) => void;
  } {
    const encoder = new TextEncoder();
    let streamController: ReadableStreamDefaultController<Uint8Array>;
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        streamController = controller;
      },
    });
    return {
      response: new Response(stream, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
      push: (chunk: string) => streamController.enqueue(encoder.encode(chunk)),
    };
  }

  function lastPermissionRequestUpdate(
    updates: unknown[],
  ): { requestId: string } | undefined {
    return [...updates]
      .reverse()
      .find(
        (u): u is { kind: string; requestId: string } =>
          typeof u === "object" &&
          u !== null &&
          (u as { kind?: string }).kind === "permission_request",
      );
  }

  function commandPosts(): unknown[] {
    return mockNetFetch.mock.calls
      .filter(([url]) => (url as string).includes("/command/"))
      .map(([, init]) => JSON.parse((init as RequestInit).body as string));
  }

  function watchRun(runId: string): void {
    mockNetFetch.mockResolvedValueOnce(
      createJsonResponse({
        id: runId,
        status: "in_progress",
        stage: null,
        output: null,
        error_message: null,
        branch: "main",
        updated_at: "2026-01-01T00:00:00Z",
      }),
    );
    relayService.watch({
      taskId: "task-1",
      runId,
      apiHost: "https://app.example.com",
      teamId: 2,
      resumeFromEntryCount: 0,
    });
  }

  it("drops a relay request for a server the run never designated", async () => {
    mockStreamFetch.mockResolvedValueOnce(
      createOpenSseResponse(mcpRequestSseLine({ server: "slack" })),
    );
    relayService.designateRelayedMcpServers("run-1", ["grafana"]);
    watchRun("run-1");

    await waitFor(() => mockStreamFetch.mock.calls.length > 0);
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(mcpRelayExecutor.execute).not.toHaveBeenCalled();
  });

  it("executes a designated relay request exactly once and posts mcp_response", async () => {
    mockStreamFetch.mockResolvedValueOnce(
      createOpenSseResponse(
        mcpRequestSseLine({ requestId: "req-1", server: "slack" }) +
          mcpRequestSseLine({ requestId: "req-1", server: "slack" }),
      ),
    );
    mockNetFetch.mockResolvedValueOnce(createJsonResponse({ result: {} }));
    relayService.designateRelayedMcpServers("run-1", ["slack"]);
    watchRun("run-1");

    await waitFor(() => mcpRelayExecutor.execute.mock.calls.length > 0);
    // The duplicate line above must not trigger a second execution.
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(mcpRelayExecutor.execute).toHaveBeenCalledOnce();
    expect(mcpRelayExecutor.execute).toHaveBeenCalledWith(
      "run-1",
      "slack",
      expect.objectContaining({ method: "initialize" }),
    );

    await waitFor(() =>
      mockNetFetch.mock.calls.some(([url]) =>
        (url as string).includes("/command/"),
      ),
    );
    const commandCall = mockNetFetch.mock.calls.find(([url]) =>
      (url as string).includes("/command/"),
    );
    const body = JSON.parse((commandCall?.[1] as RequestInit).body as string);
    expect(body).toEqual(
      expect.objectContaining({
        method: "mcp_response",
        params: {
          requestId: "req-1",
          server: "slack",
          payload: { jsonrpc: "2.0", id: 1, result: {} },
        },
      }),
    );
  });

  it.each([
    "initialize",
    "notifications/initialized",
    "ping",
    "tools/list",
    "prompts/list",
    "resources/list",
    "resources/templates/list",
  ])("executes the %s relay method without approval", async (method) => {
    const updates: unknown[] = [];
    relayService.on(CloudTaskEvent.Update, (payload) => {
      updates.push(payload);
    });
    mockStreamFetch.mockResolvedValueOnce(
      createOpenSseResponse(
        mcpRequestSseLine({
          payload: { jsonrpc: "2.0", id: 1, method },
        }),
      ),
    );
    relayService.designateRelayedMcpServers("run-1", ["slack"]);
    watchRun("run-1");

    await waitFor(() => mcpRelayExecutor.execute.mock.calls.length > 0);

    expect(lastPermissionRequestUpdate(updates)).toBeUndefined();
  });

  it("evicts a run's relay designation once the run reaches a terminal status", async () => {
    mockStreamFetch.mockResolvedValueOnce(
      createOpenSseResponse(
        `data: ${JSON.stringify({
          type: "task_run_state",
          status: "completed",
          updated_at: "2026-01-01T00:00:01Z",
        })}\n\n${mcpRequestSseLine({ server: "slack" })}`,
      ),
    );
    relayService.designateRelayedMcpServers("run-1", ["slack"]);
    watchRun("run-1");

    await waitFor(() => mockStreamFetch.mock.calls.length > 0);
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(mcpRelayExecutor.execute).not.toHaveBeenCalled();
  });

  it("drops an expired relay request without executing it", async () => {
    mockStreamFetch.mockResolvedValueOnce(
      createOpenSseResponse(
        mcpRequestSseLine({
          server: "slack",
          expiresAt: new Date(Date.now() - 60_000).toISOString(),
        }),
      ),
    );
    relayService.designateRelayedMcpServers("run-1", ["slack"]);
    watchRun("run-1");

    await waitFor(() => mockStreamFetch.mock.calls.length > 0);
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(mcpRelayExecutor.execute).not.toHaveBeenCalled();
  });

  it("sends no mcp_response for a fire-and-forget relay execution", async () => {
    mcpRelayExecutor.execute.mockResolvedValueOnce({});
    mockStreamFetch.mockResolvedValueOnce(
      createOpenSseResponse(mcpRequestSseLine({ server: "slack" })),
    );
    relayService.designateRelayedMcpServers("run-1", ["slack"]);
    watchRun("run-1");

    await waitFor(() => mcpRelayExecutor.execute.mock.calls.length > 0);
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(
      mockNetFetch.mock.calls.some(([url]) =>
        (url as string).includes("/command/"),
      ),
    ).toBe(false);
  });

  it("posts a -32000 mcp_response when the executor throws", async () => {
    mcpRelayExecutor.execute.mockRejectedValueOnce(new Error("spawn failed"));
    mockStreamFetch.mockResolvedValueOnce(
      createOpenSseResponse(
        mcpRequestSseLine({ requestId: "req-1", server: "slack" }),
      ),
    );
    mockNetFetch.mockResolvedValueOnce(createJsonResponse({ result: {} }));
    relayService.designateRelayedMcpServers("run-1", ["slack"]);
    watchRun("run-1");

    await waitFor(() =>
      mockNetFetch.mock.calls.some(([url]) =>
        (url as string).includes("/command/"),
      ),
    );
    const commandCall = mockNetFetch.mock.calls.find(([url]) =>
      (url as string).includes("/command/"),
    );
    const body = JSON.parse((commandCall?.[1] as RequestInit).body as string);
    // A thrown executor error must still answer the sandbox — otherwise it hangs to timeout.
    expect(body).toEqual(
      expect.objectContaining({
        method: "mcp_response",
        params: {
          requestId: "req-1",
          server: "slack",
          error: { code: -32000, message: "spawn failed" },
        },
      }),
    );
  });

  it("closes the run's relay connections when the run is unwatched", async () => {
    mockStreamFetch.mockResolvedValue(createOpenSseResponse(""));
    relayService.designateRelayedMcpServers("run-1", ["slack"]);
    watchRun("run-1");
    await waitFor(() => mockStreamFetch.mock.calls.length > 0);

    relayService.unwatch("task-1", "run-1");
    await waitFor(() => mcpRelayExecutor.closeRun.mock.calls.length > 0);

    expect(mcpRelayExecutor.closeRun).toHaveBeenCalledWith("run-1");
  });

  describe("relayed MCP request approval", () => {
    it.each([
      "resources/read",
      "prompts/get",
      "resources/subscribe",
      "custom/mutate",
    ])("requires desktop approval for %s", async (method) => {
      const updates: unknown[] = [];
      relayService.on(CloudTaskEvent.Update, (payload) => {
        updates.push(payload);
      });
      mockStreamFetch.mockResolvedValueOnce(
        createOpenSseResponse(
          mcpRequestSseLine({
            payload: {
              jsonrpc: "2.0",
              id: 1,
              method,
              params: { uri: "file:///private" },
            },
          }),
        ),
      );
      relayService.designateRelayedMcpServers("run-1", ["slack"]);
      watchRun("run-1");

      await waitFor(() => lastPermissionRequestUpdate(updates) !== undefined);

      expect(mcpRelayExecutor.execute).not.toHaveBeenCalled();
    });

    it("executes a non-tool request after desktop approval", async () => {
      const updates: unknown[] = [];
      relayService.on(CloudTaskEvent.Update, (payload) => {
        updates.push(payload);
      });
      mockNetFetch.mockResolvedValue(createJsonResponse({ result: {} }));
      mockStreamFetch.mockResolvedValueOnce(
        createOpenSseResponse(
          mcpRequestSseLine({
            payload: {
              jsonrpc: "2.0",
              id: 1,
              method: "resources/read",
              params: { uri: "file:///private" },
            },
          }),
        ),
      );
      relayService.designateRelayedMcpServers("run-1", ["slack"]);
      watchRun("run-1");

      await waitFor(() => lastPermissionRequestUpdate(updates) !== undefined);
      const prompt = lastPermissionRequestUpdate(updates);
      await relayService.sendCommand({
        taskId: "task-1",
        runId: "run-1",
        apiHost: "https://app.example.com",
        teamId: 2,
        method: "permission_response",
        params: { requestId: prompt?.requestId, optionId: "allow" },
      });

      await waitFor(() => mcpRelayExecutor.execute.mock.calls.length > 0);

      expect(mcpRelayExecutor.execute).toHaveBeenCalledWith(
        "run-1",
        "slack",
        expect.objectContaining({ method: "resources/read" }),
      );
    });

    it("prompts on the desktop and executes after the user allows", async () => {
      const updates: unknown[] = [];
      relayService.on(CloudTaskEvent.Update, (payload) => {
        updates.push(payload);
      });
      mockNetFetch.mockResolvedValue(createJsonResponse({ result: {} }));
      mockStreamFetch.mockResolvedValueOnce(
        createOpenSseResponse(
          mcpRequestSseLine({ payload: toolsCallPayload() }),
        ),
      );
      relayService.designateRelayedMcpServers("run-1", ["slack"]);
      watchRun("run-1");

      await waitFor(() => lastPermissionRequestUpdate(updates) !== undefined);
      expect(mcpRelayExecutor.execute).not.toHaveBeenCalled();

      const prompt = lastPermissionRequestUpdate(updates);
      await relayService.sendCommand({
        taskId: "task-1",
        runId: "run-1",
        apiHost: "https://app.example.com",
        teamId: 2,
        method: "permission_response",
        params: { requestId: prompt?.requestId, optionId: "allow" },
      });

      await waitFor(() => mcpRelayExecutor.execute.mock.calls.length > 0);
      expect(mcpRelayExecutor.execute).toHaveBeenCalledWith(
        "run-1",
        "slack",
        expect.objectContaining({ method: "tools/call" }),
      );
      await waitFor(() =>
        commandPosts().some(
          (body) => (body as { method?: string }).method === "mcp_response",
        ),
      );
    });

    it("answers a denial to the sandbox without executing, carrying the user's feedback", async () => {
      const updates: unknown[] = [];
      relayService.on(CloudTaskEvent.Update, (payload) => {
        updates.push(payload);
      });
      mockNetFetch.mockResolvedValue(createJsonResponse({ result: {} }));
      mockStreamFetch.mockResolvedValueOnce(
        createOpenSseResponse(
          mcpRequestSseLine({ payload: toolsCallPayload() }),
        ),
      );
      relayService.designateRelayedMcpServers("run-1", ["slack"]);
      watchRun("run-1");

      await waitFor(() => lastPermissionRequestUpdate(updates) !== undefined);
      const prompt = lastPermissionRequestUpdate(updates);
      await relayService.sendCommand({
        taskId: "task-1",
        runId: "run-1",
        apiHost: "https://app.example.com",
        teamId: 2,
        method: "permission_response",
        params: {
          requestId: prompt?.requestId,
          optionId: "reject",
          customInput: "use the announcements channel instead",
        },
      });

      await waitFor(() =>
        commandPosts().some(
          (body) => (body as { method?: string }).method === "mcp_response",
        ),
      );
      expect(mcpRelayExecutor.execute).not.toHaveBeenCalled();
      const response = commandPosts().find(
        (body) => (body as { method?: string }).method === "mcp_response",
      ) as { params: { error?: { message?: string } } };
      expect(response.params.error?.message).toContain(
        "use the announcements channel instead",
      );
    });

    it("drops an unanswered prompt at the request's expiry without executing", async () => {
      const updates: unknown[] = [];
      relayService.on(CloudTaskEvent.Update, (payload) => {
        updates.push(payload);
      });
      mockNetFetch.mockResolvedValue(createJsonResponse({ result: {} }));
      mockStreamFetch.mockResolvedValueOnce(
        createOpenSseResponse(
          mcpRequestSseLine({
            payload: toolsCallPayload(),
            expiresAt: new Date(Date.now() + 150).toISOString(),
          }),
        ),
      );
      relayService.designateRelayedMcpServers("run-1", ["slack"]);
      watchRun("run-1");

      await waitFor(() => lastPermissionRequestUpdate(updates) !== undefined);
      await new Promise((resolve) => setTimeout(resolve, 300));

      expect(mcpRelayExecutor.execute).not.toHaveBeenCalled();
      expect(
        commandPosts().some(
          (body) => (body as { method?: string }).method === "mcp_response",
        ),
      ).toBe(false);
    });

    it("does not derive local approval from sandbox-controlled permission options", async () => {
      const updates: unknown[] = [];
      relayService.on(CloudTaskEvent.Update, (payload) => {
        updates.push(payload);
      });
      mockNetFetch.mockResolvedValue(createJsonResponse({ result: {} }));
      const { response, push } = createControllableSseResponse();
      mockStreamFetch.mockResolvedValueOnce(response);
      relayService.designateRelayedMcpServers("run-1", ["slack"]);
      watchRun("run-1");
      await waitFor(() => mockStreamFetch.mock.calls.length > 0);

      push(
        `data: ${JSON.stringify({
          type: "permission_request",
          requestId: "harness-req-1",
          toolCall: {
            toolCallId: "tc-1",
            title: "The agent wants to call send_message (slack)",
            kind: "other",
            rawInput: {
              channel: "#general",
              toolName: "mcp__slack__send_message",
            },
          },
          options: [{ kind: "allow_once", name: "No", optionId: "reject" }],
        })}\n\n`,
      );
      await waitFor(() => lastPermissionRequestUpdate(updates) !== undefined);

      await relayService.sendCommand({
        taskId: "task-1",
        runId: "run-1",
        apiHost: "https://app.example.com",
        teamId: 2,
        method: "permission_response",
        params: { requestId: "harness-req-1", optionId: "reject" },
      });

      const updatesBeforeCall = updates.length;
      push(mcpRequestSseLine({ payload: toolsCallPayload() }));
      await waitFor(
        () =>
          updates
            .slice(updatesBeforeCall)
            .filter(
              (u) => (u as { kind?: string }).kind === "permission_request",
            ).length > 0,
      );

      expect(mcpRelayExecutor.execute).not.toHaveBeenCalled();

      const desktopPrompt = lastPermissionRequestUpdate(updates);
      await relayService.sendCommand({
        taskId: "task-1",
        runId: "run-1",
        apiHost: "https://app.example.com",
        teamId: 2,
        method: "permission_response",
        params: { requestId: desktopPrompt?.requestId, optionId: "allow" },
      });

      await waitFor(() => mcpRelayExecutor.execute.mock.calls.length > 0);
    });

    it("an always-allow answer covers subsequent calls to the same tool", async () => {
      const updates: unknown[] = [];
      relayService.on(CloudTaskEvent.Update, (payload) => {
        updates.push(payload);
      });
      mockNetFetch.mockResolvedValue(createJsonResponse({ result: {} }));
      const { response, push } = createControllableSseResponse();
      mockStreamFetch.mockResolvedValueOnce(response);
      relayService.designateRelayedMcpServers("run-1", ["slack"]);
      watchRun("run-1");
      await waitFor(() => mockStreamFetch.mock.calls.length > 0);

      push(mcpRequestSseLine({ payload: toolsCallPayload() }));
      await waitFor(() => lastPermissionRequestUpdate(updates) !== undefined);
      const prompt = lastPermissionRequestUpdate(updates);
      await relayService.sendCommand({
        taskId: "task-1",
        runId: "run-1",
        apiHost: "https://app.example.com",
        teamId: 2,
        method: "permission_response",
        params: { requestId: prompt?.requestId, optionId: "allow_always" },
      });
      await waitFor(() => mcpRelayExecutor.execute.mock.calls.length === 1);

      const updatesAfterFirst = updates.length;
      // Different arguments — always-allow is per tool, not per exact call.
      push(
        mcpRequestSseLine({
          requestId: "req-2",
          payload: toolsCallPayload({ channel: "#random" }),
        }),
      );
      await waitFor(() => mcpRelayExecutor.execute.mock.calls.length === 2);
      expect(
        updates
          .slice(updatesAfterFirst)
          .filter(
            (u) => (u as { kind?: string }).kind === "permission_request",
          ),
      ).toEqual([]);
    });
  });
});
