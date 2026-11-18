import { API_DOWNLOAD_TIMEOUT_MS } from "@posthog/agent-contracts";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PostHogAPIClient } from "./posthog-api";

const mockFetch = vi.fn();

vi.stubGlobal("fetch", mockFetch);

describe("PostHogAPIClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it.each([
    [
      "keeps known and backend-only fields",
      { reasoning_effort: "xhigh", backend_only: "kept" },
      { reasoning_effort: "xhigh", backend_only: "kept" },
    ],
    [
      "drops an unreadable reasoning effort",
      { reasoning_effort: 123, initial_prompt_override: "run this" },
      { initial_prompt_override: "run this" },
    ],
    [
      "drops an unreadable permission mode",
      { initial_permission_mode: "invented", prewarmed: true },
      { prewarmed: true },
    ],
    ["falls back to an empty state", null, {}],
  ])("reads task-run state and %s", async (_label, state, expected) => {
    const client = new PostHogAPIClient({
      apiUrl: "https://app.posthog.com",
      getApiKey: vi.fn().mockResolvedValue("token"),
      projectId: 1,
    });
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: vi.fn().mockResolvedValue({ id: "run-1", state }),
    });

    const run = await client.getTaskRun("task-1", "run-1");

    expect(run.state).toEqual(expected);
  });

  it("refreshes once when fetching task run logs gets an auth failure", async () => {
    const getApiKey = vi.fn().mockResolvedValue("stale-token");
    const refreshApiKey = vi.fn().mockResolvedValue("fresh-token");
    const client = new PostHogAPIClient({
      apiUrl: "https://app.posthog.com",
      getApiKey,
      refreshApiKey,
      projectId: 1,
    });

    mockFetch
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        statusText: "Unauthorized",
      })
      .mockResolvedValueOnce({
        ok: true,
        text: vi
          .fn()
          .mockResolvedValue(
            `${JSON.stringify({ type: "notification", notification: { method: "foo" } })}\n`,
          ),
      });

    const logs = await client.fetchTaskRunLogs({
      id: "run-1",
      task: "task-1",
    } as never);

    expect(logs).toHaveLength(1);
    expect(getApiKey).toHaveBeenCalledTimes(1);
    expect(refreshApiKey).toHaveBeenCalledTimes(1);
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("does not refresh or retry when the API answers 403", async () => {
    // A 403 is a permission denial a fresh token cannot fix. Forcing a
    // refresh on each one rotates the refresh token and rebuilds the whole
    // desktop session, which unmounts the app into its loading screen.
    const getApiKey = vi.fn().mockResolvedValue("token");
    const refreshApiKey = vi.fn().mockResolvedValue("fresh-token");
    const client = new PostHogAPIClient({
      apiUrl: "https://app.posthog.com",
      getApiKey,
      refreshApiKey,
      projectId: 1,
    });
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 403,
      statusText: "Forbidden",
      json: vi.fn().mockResolvedValue({ detail: "forbidden" }),
    });

    await expect(client.getTaskRun("task-1", "run-1")).rejects.toThrow("[403]");

    expect(refreshApiKey).not.toHaveBeenCalled();
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  // The lookup gates session start, so a stalled socket must degrade to null
  // rather than hang. The bound is what makes the best-effort catch reachable.
  it("bounds the user-node lookup and returns null when it times out", async () => {
    const client = new PostHogAPIClient({
      apiUrl: "https://app.posthog.com",
      getApiKey: vi.fn().mockResolvedValue("token"),
      projectId: 1,
    });
    mockFetch.mockRejectedValue(
      new DOMException("The operation was aborted.", "TimeoutError"),
    );

    await expect(client.getUserNode()).resolves.toBeNull();

    const init = mockFetch.mock.calls[0]?.[1] as RequestInit | undefined;
    expect(init?.signal).toBeInstanceOf(AbortSignal);
  });

  it("loads policies for managed MCP servers and keeps unmanaged servers", async () => {
    const client = new PostHogAPIClient({
      apiUrl: "https://app.posthog.com",
      getApiKey: vi.fn().mockResolvedValue("token"),
      projectId: 7,
    });
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: vi.fn().mockResolvedValue({
        results: [
          {
            tool_name: "search",
            approval_state: "needs_approval",
            description: "Search resources",
          },
        ],
      }),
    });

    await expect(
      client.getMcpRuntimeConfiguration([
        {
          type: "http",
          name: "Cloudflare",
          url: "https://app.posthog.com/api/environments/7/mcp_server_installations/installation-1/proxy/",
          headers: [],
        },
        {
          type: "http",
          name: "custom",
          url: "https://mcp.example.com/mcp",
          headers: [],
        },
      ]),
    ).resolves.toEqual({
      servers: [
        expect.objectContaining({ name: "Cloudflare" }),
        expect.objectContaining({ name: "custom" }),
      ],
      policies: [
        {
          serverName: "Cloudflare",
          toolName: "search",
          installationId: "installation-1",
          approvalState: "needs_approval",
          description: "Search resources",
        },
      ],
    });
  });

  it("omits a managed MCP server when its policies cannot be loaded", async () => {
    const client = new PostHogAPIClient({
      apiUrl: "https://app.posthog.com",
      getApiKey: vi.fn().mockResolvedValue("token"),
      projectId: 7,
    });
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: "Server error",
      json: vi.fn().mockResolvedValue({ detail: "failed" }),
    });

    const configuration = await client.getMcpRuntimeConfiguration([
      {
        type: "http",
        name: "broken",
        url: "https://app.posthog.com/api/environments/7/mcp_server_installations/installation-1/proxy/",
        headers: [],
      },
    ]);

    expect(configuration).toEqual({ servers: [], policies: [] });
  });

  it("downloads artifacts through the backend endpoint", async () => {
    const client = new PostHogAPIClient({
      apiUrl: "https://app.posthog.com",
      getApiKey: vi.fn().mockResolvedValue("token"),
      projectId: 7,
    });
    const bytes = new TextEncoder().encode("hello world");

    mockFetch.mockResolvedValueOnce({
      ok: true,
      arrayBuffer: vi.fn().mockResolvedValue(bytes.buffer),
    });

    const artifact = await client.downloadArtifact(
      "task-1",
      "run-1",
      "tasks/artifacts/team_1/task_task-1/run_run-1/file.txt",
    );

    expect(artifact).toEqual(bytes.buffer);
    expect(mockFetch).toHaveBeenCalledWith(
      "https://app.posthog.com/api/projects/7/tasks/task-1/runs/run-1/artifacts/download/",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          storage_path: "tasks/artifacts/team_1/task_task-1/run_run-1/file.txt",
        }),
        headers: expect.any(Headers),
      }),
    );
  });

  it.each([
    [
      "downloadArtifact",
      (client: PostHogAPIClient) =>
        client.downloadArtifact("task-1", "run-1", "tasks/artifacts/file.txt"),
    ],
    [
      "fetchTaskRunLogs",
      (client: PostHogAPIClient) =>
        client.fetchTaskRunLogs({ id: "run-1", task: "task-1" } as never),
    ],
  ])("gives %s the download timeout", async (_method, call) => {
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const client = new PostHogAPIClient({
      apiUrl: "https://app.posthog.com",
      getApiKey: vi.fn().mockResolvedValue("token"),
      projectId: 7,
    });
    mockFetch.mockResolvedValueOnce({
      ok: true,
      arrayBuffer: vi.fn().mockResolvedValue(new ArrayBuffer(0)),
      text: vi.fn().mockResolvedValue(""),
    });

    await call(client);

    const init = mockFetch.mock.calls[0]?.[1] as RequestInit | undefined;
    expect(timeout.mock.calls).toEqual([[API_DOWNLOAD_TIMEOUT_MS]]);
    expect(init?.signal).toBe(timeout.mock.results[0]?.value);
  });

  it.each([
    [
      "includes message_id, text_parts and trace_id when provided",
      ["part one", "final answer"],
      "msg-1",
      "f960aead-b2af-4ee0-b0eb-630109a1b2a0",
      {
        text: "final answer",
        text_parts: ["part one", "final answer"],
        message_id: "msg-1",
        trace_id: "f960aead-b2af-4ee0-b0eb-630109a1b2a0",
      },
    ],
    [
      "omits optional fields when unknown",
      undefined,
      undefined,
      undefined,
      { text: "final answer" },
    ],
  ])(
    "relay_message body %s",
    async (_label, textParts, messageId, traceId, expectedBody) => {
      const client = new PostHogAPIClient({
        apiUrl: "https://app.posthog.com",
        getApiKey: vi.fn().mockResolvedValue("token"),
        projectId: 7,
      });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({ status: "ok" }),
      });

      await client.relayMessage(
        "task-1",
        "run-1",
        "final answer",
        textParts,
        messageId,
        traceId,
      );

      expect(mockFetch).toHaveBeenCalledWith(
        "https://app.posthog.com/api/projects/7/tasks/task-1/runs/run-1/relay_message/",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify(expectedBody),
        }),
      );
    },
  );

  it("loads and atomically replaces the durable task session", async () => {
    const client = new PostHogAPIClient({
      apiUrl: "https://app.posthog.com",
      getApiKey: vi.fn().mockResolvedValue("token"),
      projectId: 7,
    });
    const content = '{"type":"session"}\n';
    const access = {
      id: "session-1",
      download_url: "https://storage.example/session.jsonl",
      content_sha256: "old-hash",
    };
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue(access),
      })
      .mockResolvedValueOnce({
        ok: true,
        text: vi.fn().mockResolvedValue(content),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({
          id: "session-1",
          content_sha256: "new-hash",
        }),
      });

    const storage = await client.getTaskSession("task-1", "run-1");
    await expect(client.downloadTaskSession(storage)).resolves.toBe(content);
    await expect(
      client.syncTaskSession(
        "task-1",
        "run-1",
        "sandbox-1",
        "old-hash",
        content,
        "task-run-token",
      ),
    ).resolves.toBe("new-hash");

    expect(mockFetch).toHaveBeenLastCalledWith(
      "https://app.posthog.com/api/projects/7/tasks/task-1/runs/run-1/task_session_sync/",
      expect.objectContaining({ method: "POST", body: content }),
    );
    const request = mockFetch.mock.calls.at(-1)?.[1] as RequestInit;
    const headers = request.headers as Headers;
    expect(headers.get("Content-Type")).toBe("application/octet-stream");
    expect(headers.get("If-Match")).toBe('"old-hash"');
    expect(headers.get("X-Sandbox-ID")).toBe("sandbox-1");
    expect(headers.get("X-Task-Run-Token")).toBe("task-run-token");
  });

  it("treats a task session without stored JSONL as empty", async () => {
    const client = new PostHogAPIClient({
      apiUrl: "https://app.posthog.com",
      getApiKey: vi.fn().mockResolvedValue("token"),
      projectId: 7,
    });

    await expect(
      client.downloadTaskSession({
        id: "session-1",
        download_url: null,
        content_sha256: null,
      }),
    ).resolves.toBe("");
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("treats a missing stored task session object as empty", async () => {
    const client = new PostHogAPIClient({
      apiUrl: "https://app.posthog.com",
      getApiKey: vi.fn().mockResolvedValue("token"),
      projectId: 7,
    });
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      statusText: "Not Found",
    });

    await expect(
      client.downloadTaskSession({
        id: "session-1",
        download_url: "https://storage.example/missing.jsonl",
        content_sha256: "old-hash",
      }),
    ).resolves.toBe("");
  });

  it("surfaces an uncertain task session replacement without retrying", async () => {
    const client = new PostHogAPIClient({
      apiUrl: "https://app.posthog.com",
      getApiKey: vi.fn().mockResolvedValue("token"),
      projectId: 7,
    });
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 504,
      statusText: "Gateway Timeout",
      text: vi.fn().mockResolvedValue("Gateway Timeout"),
    });

    await expect(
      client.syncTaskSession(
        "task-1",
        "run-1",
        "sandbox-1",
        null,
        '{"type":"session"}\n',
        "task-run-token",
      ),
    ).rejects.toThrow("Failed to sync task session: [504] Gateway Timeout");
    expect(mockFetch).toHaveBeenCalledOnce();
  });

  it.each([
    new TypeError("fetch failed"),
    new DOMException("The request timed out", "TimeoutError"),
  ])("classifies a token transport failure as retryable: %s", async (error) => {
    const client = new PostHogAPIClient({
      apiUrl: "https://app.posthog.com",
      getApiKey: vi.fn().mockResolvedValue("token"),
      projectId: 7,
    });
    mockFetch.mockRejectedValueOnce(error);

    await expect(
      client.requestCodexSubscriptionToken(
        "task-1",
        "run-1",
        "run-token",
        null,
        5_000,
      ),
    ).rejects.toMatchObject({
      name: "CodexSubscriptionTokenError",
      code: "request_failed",
    });
  });

  it("asks the run's subscription_token endpoint with the fd 3 run token", async () => {
    const client = new PostHogAPIClient({
      apiUrl: "https://app.posthog.com",
      getApiKey: vi.fn().mockResolvedValue("token"),
      projectId: 7,
    });
    const grant = {
      access_token: "chatgpt-access",
      account_id: "acct-1",
      plan_type: "plus",
      expires_at: "2030-01-01T00:00:00Z",
    };
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue(grant),
    });

    await expect(
      client.requestCodexSubscriptionToken(
        "task-1",
        "run-1",
        "run-token",
        "a".repeat(64),
        5_000,
      ),
    ).resolves.toEqual(grant);

    expect(mockFetch).toHaveBeenLastCalledWith(
      "https://app.posthog.com/api/projects/7/tasks/task-1/runs/run-1/subscription_token/",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          rejected_access_token_sha256: "a".repeat(64),
        }),
      }),
    );
    const request = mockFetch.mock.calls.at(-1)?.[1] as RequestInit;
    expect((request.headers as Headers).get("X-Task-Run-Token")).toBe(
      "run-token",
    );
  });

  it.each([
    [409, { code: "reauth_required", error: "Reconnect." }, "reauth_required"],
    [
      502,
      { code: "openai_unavailable", error: "No answer." },
      "openai_unavailable",
    ],
    [403, {}, "forbidden"],
    [500, {}, "request_failed"],
  ])(
    "maps a %s from subscription_token to the %s error code",
    async (status, body, code) => {
      const client = new PostHogAPIClient({
        apiUrl: "https://app.posthog.com",
        getApiKey: vi.fn().mockResolvedValue("token"),
        projectId: 7,
      });
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status,
        statusText: "Error",
        json: vi.fn().mockResolvedValue(body),
      });

      await expect(
        client.requestCodexSubscriptionToken(
          "task-1",
          "run-1",
          "run-token",
          null,
          5_000,
        ),
      ).rejects.toMatchObject({
        name: "CodexSubscriptionTokenError",
        code,
        status,
      });
    },
  );
});
