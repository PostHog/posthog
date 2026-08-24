import type { Task } from "@posthog/shared/domain-types";
import { describe, expect, it, vi } from "vitest";
import { ApiRequestError } from "./fetcher";
import {
  CloudCommandError,
  CloudUsageLimitError,
  DESKTOP_BILLING_LIMIT_ERROR_CODE,
  PostHogAPIClient,
  SESSION_LOGS_PAGE_TIMEOUT_MS,
} from "./posthog-client";

describe("PostHogAPIClient", () => {
  describe("getInsightDefinition", () => {
    it("loads the saved insight with a blocking refresh and returns its result", async () => {
      const fetch = vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            id: 1,
            short_id: "sdyR2Pn8",
            name: "Unique users per variant",
            derived_name: null,
            description: "Feature flag calls",
            query: { kind: "InsightVizNode", source: { kind: "TrendsQuery" } },
            result: [
              {
                label: "$feature_flag_called - true",
                data: [],
                days: [],
                aggregated_value: 2,
              },
            ],
            columns: null,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
      const client = new PostHogAPIClient(
        "https://app.posthog.test",
        async () => "token",
        async () => "token",
        42,
        { fetch },
      );

      await expect(client.getInsightDefinition("sdyR2Pn8")).resolves.toEqual({
        name: "Unique users per variant",
        description: "Feature flag calls",
        query: { kind: "InsightVizNode", source: { kind: "TrendsQuery" } },
        response: {
          results: [
            {
              label: "$feature_flag_called - true",
              data: [],
              days: [],
              aggregated_value: 2,
            },
          ],
          columns: [],
        },
      });
      const url = fetch.mock.calls[0][0] as URL;
      expect(url.pathname).toBe("/api/projects/42/insights/sdyR2Pn8/");
      expect(url.searchParams.get("refresh")).toBe("blocking");
    });

    it("returns null when the saved insight does not exist", async () => {
      const fetch = vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Not found." }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      );
      const client = new PostHogAPIClient(
        "https://app.posthog.test",
        async () => "token",
        async () => "token",
        42,
        { fetch },
      );

      await expect(client.getInsightDefinition("missing")).resolves.toBeNull();
    });
  });

  describe("getEvidencePreview", () => {
    it("retrieves a person by UUID instead of taking the first search result", async () => {
      const fetch = vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            id: 1,
            uuid: "0192aaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            name: "Ann",
            distinct_ids: ["ann-1"],
            properties: { email: "ann@example.com" },
            created_at: "2024-01-03T10:00:00Z",
            last_seen_at: "2024-01-04T10:00:00Z",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
      const client = new PostHogAPIClient(
        "https://app.posthog.test",
        async () => "token",
        async () => "token",
        42,
        { fetch },
      );

      await expect(
        client.getEvidencePreview(
          "person",
          "0192aaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        ),
      ).resolves.toMatchObject({
        title: "Ann",
        resolvedId: "0192aaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
      });
      const url = fetch.mock.calls[0][0] as URL;
      expect(url.pathname).toBe(
        "/api/projects/42/persons/0192aaaa-bbbb-cccc-dddd-eeeeeeeeeeee/",
      );
    });

    it("resolves a UUID-shaped distinct id when retrieve-by-uuid 404s", async () => {
      const distinctId = "0192aaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
      const fetch = vi
        .fn()
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ detail: "Not found." }), {
            status: 404,
            headers: { "Content-Type": "application/json" },
          }),
        )
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({
              results: [
                {
                  id: 1,
                  uuid: "0192ffff-1111-2222-3333-444444444444",
                  name: "Ann",
                  distinct_ids: [distinctId],
                  properties: { email: "ann@example.com" },
                  created_at: "2024-01-03T10:00:00Z",
                  last_seen_at: "2024-01-04T10:00:00Z",
                },
              ],
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      const client = new PostHogAPIClient(
        "https://app.posthog.test",
        async () => "token",
        async () => "token",
        42,
        { fetch },
      );

      await expect(
        client.getEvidencePreview("person", distinctId),
      ).resolves.toMatchObject({
        title: "Ann",
        resolvedId: "0192ffff-1111-2222-3333-444444444444",
      });
      expect((fetch.mock.calls[0][0] as URL).pathname).toBe(
        `/api/projects/42/persons/${distinctId}/`,
      );
      const listUrl = fetch.mock.calls[1][0] as URL;
      expect(listUrl.pathname).toBe("/api/projects/42/persons/");
      expect(listUrl.searchParams.get("search")).toBe(distinctId);
    });
  });

  it("fetches later task pages before reporting complete results", async () => {
    const client = new PostHogAPIClient(
      "https://app.posthog.test",
      async () => "token",
      async () => "token",
      42,
    );
    const getTasksPage = vi
      .spyOn(client, "getTasksPage")
      .mockResolvedValueOnce({ tasks: [{ id: "task-1" } as Task], count: 2 })
      .mockResolvedValueOnce({ tasks: [{ id: "task-2" } as Task], count: 2 });

    await expect(
      client.getTasksWithStatus(
        { repository: "posthog/posthog" },
        { maxPages: 2 },
      ),
    ).resolves.toMatchObject({
      isComplete: true,
      tasks: [{ id: "task-1" }, { id: "task-2" }],
    });
    expect(getTasksPage).toHaveBeenNthCalledWith(1, {
      limit: 100,
      offset: 0,
      repository: "posthog/posthog",
    });
    expect(getTasksPage).toHaveBeenNthCalledWith(2, {
      limit: 100,
      offset: 1,
      repository: "posthog/posthog",
    });
  });

  it("reports partial task results after reaching the page cap", async () => {
    const client = new PostHogAPIClient(
      "https://app.posthog.test",
      async () => "token",
      async () => "token",
      42,
    );
    vi.spyOn(client, "getTasksPage")
      .mockResolvedValueOnce({ tasks: [{ id: "task-1" } as Task], count: 3 })
      .mockResolvedValueOnce({ tasks: [{ id: "task-2" } as Task], count: 3 });

    await expect(
      client.getTasksWithStatus(undefined, { maxPages: 2 }),
    ).resolves.toMatchObject({
      isComplete: false,
      tasks: [{ id: "task-1" }, { id: "task-2" }],
    });
  });

  it.each([
    ["pinned", { pinned: true }, "pinned", "true"],
    ["commented-by", { commentedBy: 17 }, "commented_by", "17"],
    ["mentions", { mentions: 19 }, "mentions", "19"],
  ])("sends the %s task-list filter", async (_name, options, param, value) => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ results: [], count: 0 }), {
        status: 200,
      }),
    );
    const client = new PostHogAPIClient(
      "https://app.posthog.test",
      async () => "token",
      async () => "token",
      42,
      { fetch },
    );

    await client.getTasksPage(options);

    const url = fetch.mock.calls[0][0] as URL;
    expect(url.pathname).toBe("/api/projects/42/tasks/");
    expect(url.searchParams.get(param)).toBe(value);
  });

  it.each([
    "user_message",
    "permission_response",
    "set_config_option",
    "cancel",
  ] as const)("sends the %s cloud run command", async (method) => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ result: { accepted: true } }), {
        status: 200,
      }),
    );
    const client = new PostHogAPIClient(
      "https://app.posthog.test",
      async () => "token",
      async () => "token",
      42,
      { fetch },
    );

    await expect(
      client.sendCloudRunCommand("task-1", "run-1", method, {
        value: "payload",
      }),
    ).resolves.toEqual({ accepted: true });

    expect(fetch).toHaveBeenCalledWith(
      new URL(
        "https://app.posthog.test/api/projects/42/tasks/task-1/runs/run-1/command/",
      ),
      expect.objectContaining({
        method: "POST",
        body: expect.any(String),
      }),
    );
    const request = fetch.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(request.body as string)).toMatchObject({
      jsonrpc: "2.0",
      method,
      params: { value: "payload" },
    });
  });

  it("throws structured cloud command errors for HTTP failures", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ error: "No active sandbox for this run" }),
        {
          status: 409,
          statusText: "Conflict",
        },
      ),
    );
    const client = new PostHogAPIClient(
      "https://app.posthog.test",
      async () => "token",
      async () => "token",
      42,
      { fetch },
    );

    const error = await client
      .sendCloudRunCommand("task-1", "run-1", "user_message")
      .catch((caught: unknown) => caught);

    expect(error).toMatchObject({
      name: "CloudCommandError",
      method: "user_message",
      status: 409,
      backendError: "No active sandbox for this run",
    });
    expect(error).toBeInstanceOf(CloudCommandError);
    expect((error as CloudCommandError).isSandboxInactive()).toBe(true);
  });

  it("throws structured cloud command errors for JSON-RPC failures", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({ error: { message: "Permission request expired" } }),
          { status: 200 },
        ),
      );
    const client = new PostHogAPIClient(
      "https://app.posthog.test",
      async () => "token",
      async () => "token",
      42,
      { fetch },
    );

    await expect(
      client.sendCloudRunCommand("task-1", "run-1", "permission_response"),
    ).rejects.toMatchObject({
      method: "permission_response",
      status: 200,
      backendError: "Permission request expired",
    });
  });

  it("preserves the legacy sendRunCommand result contract", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "Run is unavailable" }), {
        status: 503,
      }),
    );
    const client = new PostHogAPIClient(
      "https://app.posthog.test",
      async () => "token",
      async () => "token",
      42,
      { fetch },
    );

    await expect(
      client.sendRunCommand("task-1", "run-1", "set_config_option"),
    ).resolves.toEqual({
      success: false,
      error: "Cloud command 'set_config_option' failed: 503 Run is unavailable",
    });
  });

  it("cancels a cloud task run with an optional reason", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ status: "cancelled" }), { status: 200 }),
      );
    const client = new PostHogAPIClient(
      "https://app.posthog.test",
      async () => "token",
      async () => "token",
      42,
      { fetch },
    );

    await expect(
      client.cancelTaskRun("task-1", "run-1", "user requested"),
    ).resolves.toEqual({ status: "cancelled" });

    expect(fetch).toHaveBeenCalledWith(
      new URL(
        "https://app.posthog.test/api/projects/42/tasks/task-1/runs/run-1/cancel/",
      ),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ reason: "user requested" }),
      }),
    );
  });

  it("cancels a cloud task run with an empty body by default", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }));
    const client = new PostHogAPIClient(
      "https://app.posthog.test",
      async () => "token",
      async () => "token",
      42,
      { fetch },
    );

    await expect(client.cancelTaskRun("task-1", "run-1")).resolves.toEqual({});

    const request = fetch.mock.calls[0][1] as RequestInit;
    expect(request.body).toBe(JSON.stringify({}));
  });

  it("builds cloud task config from the authenticated gateway catalog", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          data: [
            {
              id: "claude-opus-4-8",
              owned_by: "anthropic",
              context_window: 200000,
              supports_streaming: true,
              supports_vision: true,
              allowed: true,
            },
            {
              id: "claude-fable-5",
              owned_by: "anthropic",
              context_window: 200000,
              supports_streaming: true,
              supports_vision: true,
              allowed: false,
            },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    const client = new PostHogAPIClient(
      "https://eu.posthog.com",
      async () => "token",
      async () => "token",
      123,
      { fetch },
    );

    const options = await client.getCloudTaskConfigOptions("claude");

    expect(fetch).toHaveBeenCalledWith(
      new URL("https://gateway.eu.posthog.com/posthog_code/v1/models"),
      expect.objectContaining({
        method: "GET",
        headers: expect.any(Headers),
      }),
    );
    const requestHeaders = fetch.mock.calls[0]?.[1]?.headers as Headers;
    expect(requestHeaders.get("X-PostHog-Project-Id")).toBe("123");
    expect(options.find((option) => option.category === "model")).toMatchObject(
      {
        currentValue: "claude-opus-4-8",
        options: [
          expect.objectContaining({ value: "claude-opus-4-8" }),
          expect.objectContaining({
            value: "claude-fable-5",
            _meta: expect.any(Object),
          }),
        ],
      },
    );
  });

  it.each([
    {
      label: "desktop default",
      options: undefined,
      expectedConnectFrom: "posthog_code",
      expectedUserAgent: "posthog/desktop.hog.dev; version: unknown",
    },
    {
      label: "mobile configuration",
      options: {
        appVersion: "1.2.3",
        userAgent: "posthog/mobile; version: 1.2.3",
        githubConnectFrom: "posthog_mobile",
      },
      expectedConnectFrom: "posthog_mobile",
      expectedUserAgent: "posthog/mobile; version: 1.2.3",
    },
  ])(
    "uses $label identity for GitHub connections",
    async ({ options, expectedConnectFrom, expectedUserAgent }) => {
      const fetch = vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ install_url: "https://github.com/login/oauth" }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
      );
      const client = new PostHogAPIClient(
        "http://localhost:8000",
        async () => "token",
        async () => "token",
        123,
        { ...options, fetch },
      );

      await expect(client.startGithubUserIntegrationConnect()).resolves.toEqual(
        {
          install_url: "https://github.com/login/oauth",
        },
      );

      expect(fetch).toHaveBeenCalledWith(
        new URL(
          "http://localhost:8000/api/users/@me/integrations/github/start/",
        ),
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            team_id: 123,
            connect_from: expectedConnectFrom,
          }),
        }),
      );
      expect(fetch.mock.calls[0][1].headers.get("User-Agent")).toBe(
        expectedUserAgent,
      );
    },
  );

  it("sends supported reasoning effort for cloud Codex runs", async () => {
    const client = new PostHogAPIClient(
      "http://localhost:8000",
      async () => "token",
      async () => "token",
      123,
    );

    const post = vi.fn().mockResolvedValue({
      id: "task-123",
      title: "Task",
      description: "Task",
      created_at: "2026-04-14T00:00:00Z",
      updated_at: "2026-04-14T00:00:00Z",
      origin_product: "user_created",
    });

    (client as unknown as { api: { post: typeof post } }).api = { post };

    await client.runTaskInCloud("task-123", "feature/max-effort", {
      adapter: "codex",
      model: "gpt-5.4",
      reasoningLevel: "high",
    });

    expect(post).toHaveBeenCalledWith(
      "/api/projects/{project_id}/tasks/{id}/run/",
      expect.objectContaining({
        path: { project_id: "123", id: "task-123" },
        body: expect.objectContaining({
          mode: "interactive",
          branch: "feature/max-effort",
          runtime_adapter: "codex",
          model: "gpt-5.4",
          reasoning_effort: "high",
        }),
      }),
    );
  });

  it("preserves Codex-native permission modes for cloud runs", async () => {
    const client = new PostHogAPIClient(
      "http://localhost:8000",
      async () => "token",
      async () => "token",
      123,
    );

    const post = vi.fn().mockResolvedValue({
      id: "task-123",
      title: "Task",
      description: "Task",
      created_at: "2026-04-14T00:00:00Z",
      updated_at: "2026-04-14T00:00:00Z",
      origin_product: "user_created",
    });

    (client as unknown as { api: { post: typeof post } }).api = { post };

    await client.runTaskInCloud("task-123", "feature/codex-mode", {
      adapter: "codex",
      model: "gpt-5.4",
      initialPermissionMode: "auto",
    });

    expect(post).toHaveBeenCalledWith(
      "/api/projects/{project_id}/tasks/{id}/run/",
      expect.objectContaining({
        body: expect.objectContaining({
          initial_permission_mode: "auto",
        }),
      }),
    );
  });

  it("preserves plan for cloud Codex runs", async () => {
    const client = new PostHogAPIClient(
      "http://localhost:8000",
      async () => "token",
      async () => "token",
      123,
    );

    const post = vi.fn().mockResolvedValue({
      id: "task-123",
      title: "Task",
      description: "Task",
      created_at: "2026-04-14T00:00:00Z",
      updated_at: "2026-04-14T00:00:00Z",
      origin_product: "user_created",
    });

    (client as unknown as { api: { post: typeof post } }).api = { post };

    await client.runTaskInCloud("task-123", "feature/codex-plan", {
      adapter: "codex",
      model: "gpt-5.4",
      initialPermissionMode: "plan",
    });

    expect(post).toHaveBeenCalledWith(
      "/api/projects/{project_id}/tasks/{id}/run/",
      expect.objectContaining({
        body: expect.objectContaining({
          initial_permission_mode: "plan",
        }),
      }),
    );
  });

  it("omits the permission mode when no adapter is set", async () => {
    const client = new PostHogAPIClient(
      "http://localhost:8000",
      async () => "token",
      async () => "token",
      123,
    );

    const post = vi.fn().mockResolvedValue({
      id: "task-123",
      title: "Task",
      description: "Task",
      created_at: "2026-04-14T00:00:00Z",
      updated_at: "2026-04-14T00:00:00Z",
      origin_product: "user_created",
    });

    (client as unknown as { api: { post: typeof post } }).api = { post };

    await client.runTaskInCloud("task-123", "feature/no-adapter", {
      initialPermissionMode: "plan",
    });

    expect(post).toHaveBeenCalledWith(
      "/api/projects/{project_id}/tasks/{id}/run/",
      expect.objectContaining({
        body: expect.not.objectContaining({
          initial_permission_mode: expect.anything(),
        }),
      }),
    );
  });

  it.each([true, false])("forwards auto publish %s", async (autoPublish) => {
    const client = new PostHogAPIClient(
      "http://localhost:8000",
      async () => "token",
      async () => "token",
      123,
    );
    const post = vi.fn().mockResolvedValue({
      id: "task-123",
      title: "Task",
      description: "Task",
      created_at: "2026-04-14T00:00:00Z",
      updated_at: "2026-04-14T00:00:00Z",
      origin_product: "user_created",
    });
    (client as unknown as { api: { post: typeof post } }).api = { post };

    await client.runTaskInCloud("task-123", null, { autoPublish });

    expect(post).toHaveBeenCalledWith(
      "/api/projects/{project_id}/tasks/{id}/run/",
      expect.objectContaining({
        body: expect.objectContaining({ auto_publish: autoPublish }),
      }),
    );
  });

  it("rejects unsupported reasoning effort for cloud Codex runs", async () => {
    const client = new PostHogAPIClient(
      "http://localhost:8000",
      async () => "token",
      async () => "token",
      123,
    );

    const post = vi.fn();
    (client as unknown as { api: { post: typeof post } }).api = { post };

    await expect(
      client.runTaskInCloud("task-123", "feature/max-effort", {
        adapter: "codex",
        model: "gpt-5.4",
        reasoningLevel: "max",
      }),
    ).rejects.toThrow(
      "Reasoning effort 'max' is not supported for codex model 'gpt-5.4'.",
    );

    expect(post).not.toHaveBeenCalled();
  });

  it.each(["high", "max"] as const)(
    "forwards supported GLM 5.2 reasoning effort %s",
    async (reasoningLevel) => {
      const client = new PostHogAPIClient(
        "http://localhost:8000",
        async () => "token",
        async () => "token",
        123,
      );

      const post = vi.fn().mockResolvedValue({ id: "run-123" });
      (client as unknown as { api: { post: typeof post } }).api = { post };

      await client.runTaskInCloud("task-123", "feature/glm-effort", {
        adapter: "claude",
        model: "@cf/zai-org/glm-5.2",
        reasoningLevel,
      });

      expect(post).toHaveBeenCalledWith(
        "/api/projects/{project_id}/tasks/{id}/run/",
        expect.objectContaining({
          body: expect.objectContaining({
            runtime_adapter: "claude",
            model: "@cf/zai-org/glm-5.2",
            reasoning_effort: reasoningLevel,
          }),
        }),
      );
    },
  );

  it("rejects unsupported minimal reasoning effort for cloud runs", async () => {
    const client = new PostHogAPIClient(
      "http://localhost:8000",
      async () => "token",
      async () => "token",
      123,
    );

    const post = vi.fn();
    (client as unknown as { api: { post: typeof post } }).api = { post };

    await expect(
      client.runTaskInCloud("task-123", "feature/legacy-effort", {
        adapter: "claude",
        model: "claude-opus-4-8",
        reasoningLevel: "minimal",
      }),
    ).rejects.toThrow(
      "Reasoning effort 'minimal' is not supported for claude model 'claude-opus-4-8'.",
    );

    expect(post).not.toHaveBeenCalled();
  });

  it("creates cloud task runs without relying on generated request typing", async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "run-123", environment: "cloud" }),
    });
    const client = new PostHogAPIClient(
      "http://localhost:8000",
      async () => "token",
      async () => "token",
      123,
    );

    (
      client as unknown as {
        api: { baseUrl: string; fetcher: { fetch: typeof fetch } };
      }
    ).api = {
      baseUrl: "http://localhost:8000",
      fetcher: { fetch },
    };

    await expect(
      client.createTaskRun("task-123", {
        environment: "cloud",
        mode: "interactive",
        branch: "feature/direct-upload",
        adapter: "codex",
        model: "gpt-5.4",
        reasoningLevel: "high",
        initialPermissionMode: "auto",
      }),
    ).resolves.toMatchObject({
      id: "run-123",
      task: "task-123",
      team: 123,
      environment: "cloud",
      status: "not_started",
    });

    expect(fetch).toHaveBeenCalledWith(
      expect.objectContaining({
        method: "post",
        path: "/api/projects/123/tasks/task-123/runs/",
        overrides: {
          body: JSON.stringify({
            mode: "interactive",
            branch: "feature/direct-upload",
            runtime_adapter: "codex",
            model: "gpt-5.4",
            reasoning_effort: "high",
            initial_permission_mode: "auto",
            environment: "cloud",
          }),
        },
      }),
    );
  });

  it("loads native task session storage access", async () => {
    const storage = {
      id: "session-1",
      download_url: "https://storage.example/session.jsonl",
      content_sha256: "hash",
    };
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => storage,
    });
    const client = new PostHogAPIClient(
      "http://localhost:8000",
      async () => "token",
      async () => "token",
      123,
    );
    (
      client as unknown as {
        api: { baseUrl: string; fetcher: { fetch: typeof fetch } };
      }
    ).api = {
      baseUrl: "http://localhost:8000",
      fetcher: { fetch },
    };

    await expect(
      client.getTaskSessionStorageAccess("task-123", "run-123"),
    ).resolves.toEqual(storage);
    expect(fetch).toHaveBeenCalledWith(
      expect.objectContaining({
        method: "get",
        path: "/api/projects/123/tasks/task-123/runs/run-123/task_session/",
      }),
    );
  });

  it("maps the permission mode per adapter when creating task runs", async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "run-123", environment: "cloud" }),
    });
    const client = new PostHogAPIClient(
      "http://localhost:8000",
      async () => "token",
      async () => "token",
      123,
    );

    (
      client as unknown as {
        api: { baseUrl: string; fetcher: { fetch: typeof fetch } };
      }
    ).api = {
      baseUrl: "http://localhost:8000",
      fetcher: { fetch },
    };

    await client.createTaskRun("task-123", {
      environment: "cloud",
      adapter: "claude",
      model: "claude-opus-4-8",
      initialPermissionMode: "read-only",
    });

    const body = JSON.parse(fetch.mock.calls[0][0].overrides.body as string);
    expect(body.initial_permission_mode).toBe("plan");
  });

  it("serializes an rtk opt-out as rtk_enabled false on run creation", async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "run-123", environment: "cloud" }),
    });
    const client = new PostHogAPIClient(
      "http://localhost:8000",
      async () => "token",
      async () => "token",
      123,
    );

    (
      client as unknown as {
        api: { baseUrl: string; fetcher: { fetch: typeof fetch } };
      }
    ).api = {
      baseUrl: "http://localhost:8000",
      fetcher: { fetch },
    };

    await client.createTaskRun("task-123", {
      environment: "cloud",
      mode: "interactive",
      rtkEnabled: false,
    });

    const request = fetch.mock.calls[0][0] as {
      overrides: { body: string };
    };
    expect(JSON.parse(request.overrides.body)).toMatchObject({
      rtk_enabled: false,
    });
  });

  it("omits the permission mode from created task runs without an adapter", async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "run-123", environment: "cloud" }),
    });
    const client = new PostHogAPIClient(
      "http://localhost:8000",
      async () => "token",
      async () => "token",
      123,
    );

    (
      client as unknown as {
        api: { baseUrl: string; fetcher: { fetch: typeof fetch } };
      }
    ).api = {
      baseUrl: "http://localhost:8000",
      fetcher: { fetch },
    };

    await client.createTaskRun("task-123", {
      environment: "cloud",
      initialPermissionMode: "plan",
    });

    const body = JSON.parse(fetch.mock.calls[0][0].overrides.body as string);
    expect(body).not.toHaveProperty("initial_permission_mode");
  });

  it("omits the permission mode when none is selected", async () => {
    const client = new PostHogAPIClient(
      "http://localhost:8000",
      async () => "token",
      async () => "token",
      123,
    );

    const post = vi.fn().mockResolvedValue({
      id: "task-123",
      title: "Task",
      description: "Task",
      created_at: "2026-04-14T00:00:00Z",
      updated_at: "2026-04-14T00:00:00Z",
      origin_product: "user_created",
    });

    (client as unknown as { api: { post: typeof post } }).api = { post };

    await client.runTaskInCloud("task-123", "feature/no-mode", {
      adapter: "codex",
      model: "gpt-5.4",
    });

    expect(post).toHaveBeenCalledWith(
      "/api/projects/{project_id}/tasks/{id}/run/",
      expect.objectContaining({
        body: expect.not.objectContaining({
          initial_permission_mode: expect.anything(),
        }),
      }),
    );
  });

  it("forwards contextWindow to the cloud run body when an adapter is set", async () => {
    const client = new PostHogAPIClient(
      "http://localhost:8000",
      async () => "token",
      async () => "token",
      123,
    );

    const post = vi.fn().mockResolvedValue({
      id: "task-123",
      title: "Task",
      description: "Task",
      created_at: "2026-04-14T00:00:00Z",
      updated_at: "2026-04-14T00:00:00Z",
      origin_product: "user_created",
    });

    (client as unknown as { api: { post: typeof post } }).api = { post };

    await client.runTaskInCloud("task-123", "feature/context-window", {
      adapter: "claude",
      model: "claude-opus-5",
      contextWindow: "1m",
    });

    expect(post).toHaveBeenCalledWith(
      "/api/projects/{project_id}/tasks/{id}/run/",
      expect.objectContaining({
        body: expect.objectContaining({ context_window: "1m" }),
      }),
    );
  });

  it.each([false, true] as const)(
    "forwards fastMode:%s to the cloud run body when an adapter is set",
    async (fastMode) => {
      const client = new PostHogAPIClient(
        "http://localhost:8000",
        async () => "token",
        async () => "token",
        123,
      );

      const post = vi.fn().mockResolvedValue({
        id: "task-123",
        title: "Task",
        description: "Task",
        created_at: "2026-04-14T00:00:00Z",
        updated_at: "2026-04-14T00:00:00Z",
        origin_product: "user_created",
      });

      (client as unknown as { api: { post: typeof post } }).api = { post };

      await client.runTaskInCloud("task-123", "feature/fast-mode", {
        adapter: "claude",
        model: "claude-opus-5",
        fastMode,
      });

      expect(post).toHaveBeenCalledWith(
        "/api/projects/{project_id}/tasks/{id}/run/",
        expect.objectContaining({
          body: expect.objectContaining({ fast_mode: fastMode }),
        }),
      );
    },
  );

  it("omits contextWindow and fastMode when no adapter is set", async () => {
    const client = new PostHogAPIClient(
      "http://localhost:8000",
      async () => "token",
      async () => "token",
      123,
    );

    const post = vi.fn().mockResolvedValue({
      id: "task-123",
      title: "Task",
      description: "Task",
      created_at: "2026-04-14T00:00:00Z",
      updated_at: "2026-04-14T00:00:00Z",
      origin_product: "user_created",
    });

    (client as unknown as { api: { post: typeof post } }).api = { post };

    await client.runTaskInCloud("task-123", "feature/no-adapter", {
      contextWindow: "1m",
      fastMode: false,
    });

    const call = post.mock.calls[0][1] as { body: Record<string, unknown> };
    expect(call.body).not.toHaveProperty("context_window");
    expect(call.body).not.toHaveProperty("fast_mode");
  });

  it("starts an existing cloud task run with run-scoped artifact ids", async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "task-123", latest_run: { id: "run-123" } }),
    });
    const client = new PostHogAPIClient(
      "http://localhost:8000",
      async () => "token",
      async () => "token",
      123,
    );

    (
      client as unknown as {
        api: { baseUrl: string; fetcher: { fetch: typeof fetch } };
      }
    ).api = {
      baseUrl: "http://localhost:8000",
      fetcher: { fetch },
    };

    await expect(
      client.startTaskRun("task-123", "run-123", {
        pendingUserMessage: "Read the attached file first",
        pendingUserArtifactIds: ["artifact-1"],
      }),
    ).resolves.toMatchObject({
      id: "task-123",
      latest_run: {
        id: "run-123",
        task: "task-123",
        team: 123,
        status: "not_started",
      },
    });

    expect(fetch).toHaveBeenCalledWith(
      expect.objectContaining({
        method: "post",
        path: "/api/projects/123/tasks/task-123/runs/run-123/start/",
        overrides: {
          body: JSON.stringify({
            pending_user_message: "Read the attached file first",
            pending_user_artifact_ids: ["artifact-1"],
          }),
        },
      }),
    );
  });

  it("registers PostHog references without file upload fields", async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        artifacts: [
          {
            id: "phref-1",
            name: "Checkout funnel",
            type: "reference",
            source: "posthog_object",
            uploaded_at: "2026-08-19T00:00:00Z",
            metadata: {
              reference_type: "posthog_object",
              object_kind: "insight",
              object_id: "9pQx3",
              source_message_ids: ["turn-1"],
              occurrence_count: 1,
            },
          },
        ],
      }),
    });
    const client = new PostHogAPIClient(
      "http://localhost:8000",
      async () => "token",
      async () => "token",
      123,
    );
    (
      client as unknown as {
        api: { baseUrl: string; fetcher: { fetch: typeof fetch } };
      }
    ).api = {
      baseUrl: "http://localhost:8000",
      fetcher: { fetch },
    };

    await expect(
      client.registerTaskRunPostHogReferences("task-123", "run-123", [
        {
          name: "Checkout funnel",
          object_kind: "insight",
          object_id: "9pQx3",
          source_message_id: "turn-1",
        },
      ]),
    ).resolves.toEqual([
      expect.objectContaining({
        id: "phref-1",
        type: "reference",
        source: "posthog_object",
        metadata: expect.objectContaining({ object_id: "9pQx3" }),
      }),
    ]);
    expect(fetch).toHaveBeenCalledWith(
      expect.objectContaining({
        method: "post",
        path: "/api/projects/123/tasks/task-123/runs/run-123/artifacts/references/",
        overrides: {
          body: JSON.stringify({
            references: [
              {
                name: "Checkout funnel",
                object_kind: "insight",
                object_id: "9pQx3",
                source_message_id: "turn-1",
              },
            ],
          }),
        },
      }),
    );
  });

  it("presigns a task run artifact for preview", async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        url: "https://s3.example.com/screenshot.png?signature=abc",
        expires_in: 3600,
      }),
    });
    const client = new PostHogAPIClient(
      "http://localhost:8000",
      async () => "token",
      async () => "token",
      123,
    );

    (
      client as unknown as {
        api: { baseUrl: string; fetcher: { fetch: typeof fetch } };
      }
    ).api = {
      baseUrl: "http://localhost:8000",
      fetcher: { fetch },
    };

    await expect(
      client.presignTaskRunArtifact(
        "task-123",
        "run-123",
        "tasks/run-123/artifacts/screenshot.png",
      ),
    ).resolves.toBe("https://s3.example.com/screenshot.png?signature=abc");
    expect(fetch).toHaveBeenCalledWith(
      expect.objectContaining({
        method: "post",
        path: "/api/projects/123/tasks/task-123/runs/run-123/artifacts/presign/",
        overrides: {
          body: JSON.stringify({
            storage_path: "tasks/run-123/artifacts/screenshot.png",
          }),
        },
      }),
    );
  });

  it("returns the redirect URL when authorizing an MCP installation", async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        redirect_url: "https://auth.example.com/authorize?state=abc",
      }),
    });
    const client = new PostHogAPIClient(
      "http://localhost:8000",
      async () => "token",
      async () => "token",
      123,
    );

    (
      client as unknown as {
        api: { baseUrl: string; fetcher: { fetch: typeof fetch } };
      }
    ).api = {
      baseUrl: "http://localhost:8000",
      fetcher: { fetch },
    };

    await expect(
      client.authorizeMcpInstallation({
        installation_id: "inst-123",
        install_source: "posthog-code",
        posthog_code_callback_url: "posthog-code://mcp-oauth-complete",
      }),
    ).resolves.toEqual({
      redirect_url: "https://auth.example.com/authorize?state=abc",
    });

    expect(fetch).toHaveBeenCalledWith(
      expect.objectContaining({
        method: "get",
        path: "/api/environments/123/mcp_server_installations/authorize/",
      }),
    );
    expect(fetch.mock.calls[0][0]).not.toHaveProperty("overrides");
  });

  describe("warmTask", () => {
    function makeClient(fetch: ReturnType<typeof vi.fn>) {
      const client = new PostHogAPIClient(
        "http://localhost:8000",
        async () => "token",
        async () => "token",
        123,
      );
      (
        client as unknown as {
          api: { baseUrl: string; fetcher: { fetch: typeof fetch } };
        }
      ).api = { baseUrl: "http://localhost:8000", fetcher: { fetch } };
      return client;
    }

    it("posts the repository + integration + branch and returns the warm run identifiers", async () => {
      const fetch = vi.fn().mockResolvedValue({
        ok: true,
        text: async () =>
          JSON.stringify({ task_id: "task-1", run_id: "run-1" }),
      });
      const client = makeClient(fetch);

      await expect(
        client.warmTask({
          repository: "PostHog/posthog",
          github_integration: 42,
          branch: "feature/warm",
        }),
      ).resolves.toEqual({ task_id: "task-1", run_id: "run-1" });

      expect(fetch).toHaveBeenCalledWith(
        expect.objectContaining({
          method: "post",
          path: "/api/projects/123/tasks/warm/",
          overrides: {
            body: JSON.stringify({
              repository: "PostHog/posthog",
              github_integration: 42,
              branch: "feature/warm",
              runtime_adapter: null,
              model: null,
              reasoning_effort: null,
            }),
          },
        }),
      );
    });

    it("forwards the selected runtime so the warm Run starts on it", async () => {
      const fetch = vi.fn().mockResolvedValue({
        ok: true,
        text: async () =>
          JSON.stringify({ task_id: "task-1", run_id: "run-1" }),
      });
      const client = makeClient(fetch);

      await client.warmTask({
        repository: "PostHog/posthog",
        github_integration: 42,
        branch: "feature/warm",
        runtime_adapter: "codex",
        model: "gpt-5.5",
        reasoning_effort: "high",
      });

      expect(fetch).toHaveBeenCalledWith(
        expect.objectContaining({
          overrides: {
            body: JSON.stringify({
              repository: "PostHog/posthog",
              github_integration: 42,
              branch: "feature/warm",
              runtime_adapter: "codex",
              model: "gpt-5.5",
              reasoning_effort: "high",
            }),
          },
        }),
      );
    });

    it("forwards the selected sandbox environment and custom image", async () => {
      const fetch = vi.fn().mockResolvedValue({
        ok: true,
        text: async () =>
          JSON.stringify({ task_id: "task-1", run_id: "run-1" }),
      });
      const client = makeClient(fetch);

      await client.warmTask({
        repository: "PostHog/posthog",
        github_integration: 42,
        sandbox_environment_id: "environment-123",
        custom_image_id: "image-123",
      });

      expect(fetch).toHaveBeenCalledWith(
        expect.objectContaining({
          overrides: {
            body: JSON.stringify({
              repository: "PostHog/posthog",
              github_integration: 42,
              branch: null,
              runtime_adapter: null,
              model: null,
              reasoning_effort: null,
              sandbox_environment_id: "environment-123",
              custom_image_id: "image-123",
            }),
          },
        }),
      );
    });

    it("sends a null branch when none is provided", async () => {
      const fetch = vi.fn().mockResolvedValue({
        ok: true,
        text: async () =>
          JSON.stringify({ task_id: "task-1", run_id: "run-1" }),
      });
      const client = makeClient(fetch);

      await client.warmTask({
        repository: "PostHog/posthog",
        github_integration: 42,
      });

      expect(fetch).toHaveBeenCalledWith(
        expect.objectContaining({
          overrides: {
            body: JSON.stringify({
              repository: "PostHog/posthog",
              github_integration: 42,
              branch: null,
              runtime_adapter: null,
              model: null,
              reasoning_effort: null,
            }),
          },
        }),
      );
    });

    it("supports warming a repo-less sandbox", async () => {
      const fetch = vi.fn().mockResolvedValue({
        ok: true,
        text: async () =>
          JSON.stringify({ task_id: "task-1", run_id: "run-1" }),
      });
      const client = makeClient(fetch);

      await client.warmTask({ repository: null, github_integration: null });

      expect(fetch).toHaveBeenCalledWith(
        expect.objectContaining({
          overrides: {
            body: JSON.stringify({
              repository: null,
              github_integration: null,
              branch: null,
              runtime_adapter: null,
              model: null,
              reasoning_effort: null,
            }),
          },
        }),
      );
    });

    it("returns null on an empty 200 body (feature disabled / capped / no-op)", async () => {
      const fetch = vi.fn().mockResolvedValue({
        ok: true,
        text: async () => "",
      });
      const client = makeClient(fetch);

      await expect(
        client.warmTask({
          repository: "PostHog/posthog",
          github_integration: 42,
        }),
      ).resolves.toBeNull();
    });

    it("throws on a non-ok response", async () => {
      const fetch = vi
        .fn()
        .mockResolvedValue({ ok: false, statusText: "Bad Request" });
      const client = makeClient(fetch);

      await expect(
        client.warmTask({
          repository: "PostHog/posthog",
          github_integration: 42,
        }),
      ).rejects.toThrow("Bad Request");
    });

    it("maps the Desktop billing denial to a cloud usage limit", async () => {
      const body = {
        type: "rate_limit",
        code: DESKTOP_BILLING_LIMIT_ERROR_CODE,
        detail: "Your organization reached its PostHog Desktop usage limit.",
      };
      const fetch = vi
        .fn()
        .mockRejectedValue(
          new ApiRequestError(429, JSON.stringify(body), body),
        );
      const client = makeClient(fetch);

      await expect(
        client.warmTask({ repository: null, github_integration: null }),
      ).rejects.toBeInstanceOf(CloudUsageLimitError);
    });

    it("does not map unrelated 429 responses to billing", async () => {
      const body = { code: "another_rate_limit" };
      const error = new ApiRequestError(429, JSON.stringify(body), body);
      const client = makeClient(vi.fn().mockRejectedValue(error));

      await expect(
        client.warmTask({ repository: null, github_integration: null }),
      ).rejects.toBe(error);
    });
  });

  describe("getSignalReport", () => {
    function makeClient(fetch: ReturnType<typeof vi.fn>) {
      const client = new PostHogAPIClient(
        "http://localhost:8000",
        async () => "token",
        async () => "token",
        123,
      );
      (
        client as unknown as {
          api: { baseUrl: string; fetcher: { fetch: typeof fetch } };
        }
      ).api = {
        baseUrl: "http://localhost:8000",
        fetcher: { fetch },
      };
      return client;
    }

    it("returns the parsed report on success", async () => {
      const fetch = vi.fn().mockResolvedValue({
        json: async () => ({ id: "abc", title: "hi" }),
      });
      const client = makeClient(fetch);

      await expect(client.getSignalReport("abc")).resolves.toEqual({
        id: "abc",
        title: "hi",
      });
    });

    it("returns null when the shared fetcher throws a 404", async () => {
      const fetch = vi
        .fn()
        .mockRejectedValue(
          new Error('Failed request: [404] {"detail":"Not found."}'),
        );
      const client = makeClient(fetch);

      await expect(client.getSignalReport("abc")).resolves.toBeNull();
    });

    it("returns null when the shared fetcher throws a 403", async () => {
      const fetch = vi
        .fn()
        .mockRejectedValue(
          new Error('Failed request: [403] {"detail":"Forbidden."}'),
        );
      const client = makeClient(fetch);

      await expect(client.getSignalReport("abc")).resolves.toBeNull();
    });

    it("rethrows non-404/403 errors", async () => {
      const fetch = vi
        .fn()
        .mockRejectedValue(new Error("Failed request: [500] boom"));
      const client = makeClient(fetch);

      await expect(client.getSignalReport("abc")).rejects.toThrow("[500]");
    });
  });

  describe("clearTaskRunConversation", () => {
    function makeClient(fetch: ReturnType<typeof vi.fn>) {
      const client = new PostHogAPIClient(
        "http://localhost:8000",
        async () => "token",
        async () => "token",
        123,
      );
      (
        client as unknown as {
          api: { baseUrl: string; fetcher: { fetch: typeof fetch } };
        }
      ).api = {
        baseUrl: "http://localhost:8000",
        fetcher: { fetch },
      };
      return client;
    }

    it("surfaces the backend's clean error message", async () => {
      const fetch = vi
        .fn()
        .mockRejectedValue(
          new Error(
            'Failed request: [409] {"error":"Run is still active; send /clear to its agent instead"}',
          ),
        );
      const client = makeClient(fetch);

      await expect(
        client.clearTaskRunConversation("task-1", "run-1"),
      ).rejects.toThrow(
        "Run is still active; send /clear to its agent instead",
      );
    });

    it("falls back to a status-coded message on an older backend's generic 404", async () => {
      // A pre-#76943 backend has no clear_conversation route, so DRF's router
      // returns its generic {"detail":"Not found."} rather than a message
      // this endpoint controls. Surfacing that verbatim would read as "Not
      // found." with no indication a clear was attempted or what to do next.
      const fetch = vi
        .fn()
        .mockRejectedValue(
          new Error('Failed request: [404] {"detail":"Not found."}'),
        );
      const client = makeClient(fetch);

      await expect(
        client.clearTaskRunConversation("task-1", "run-1"),
      ).rejects.toThrow("Couldn’t clear the conversation. (HTTP 404)");
    });
  });

  describe("getTaskSummaries", () => {
    const SUMMARIES_PATH = "/api/projects/123/tasks/summaries/";

    function buildClient(fetch: ReturnType<typeof vi.fn>) {
      const client = new PostHogAPIClient(
        "http://localhost:8000",
        async () => "token",
        async () => "token",
        123,
      );
      (
        client as unknown as {
          api: { baseUrl: string; fetcher: { fetch: typeof fetch } };
        }
      ).api = { baseUrl: "http://localhost:8000", fetcher: { fetch } };
      return client;
    }

    function page(results: object[], next: string | null = null) {
      return {
        ok: true,
        json: async () => ({ count: 0, previous: null, next, results }),
      };
    }

    function buildFetchForPages(...pages: ReturnType<typeof page>[]) {
      const fetch = vi.fn();
      for (const p of pages) fetch.mockResolvedValueOnce(p);
      return fetch;
    }

    it("returns immediately for empty input without hitting the network", async () => {
      const fetch = vi.fn();
      await expect(buildClient(fetch).getTaskSummaries([])).resolves.toEqual(
        [],
      );
      expect(fetch).not.toHaveBeenCalled();
    });

    it("returns single-page results without further requests", async () => {
      const fetch = buildFetchForPages(page([{ id: "a" }]));
      await expect(buildClient(fetch).getTaskSummaries(["a"])).resolves.toEqual(
        [{ id: "a" }],
      );
      expect(fetch).toHaveBeenCalledTimes(1);
    });

    it.each([
      {
        name: "same-host next URL",
        nextUrl: `http://localhost:8000${SUMMARIES_PATH}?limit=2&offset=2`,
        expectedSecondPath: `${SUMMARIES_PATH}?limit=2&offset=2`,
      },
      {
        name: "cross-host next URL (proxy variance)",
        nextUrl: `https://internal.posthog.example${SUMMARIES_PATH}?limit=1&offset=1`,
        expectedSecondPath: `${SUMMARIES_PATH}?limit=1&offset=1`,
      },
    ])(
      "follows the next cursor across pages and merges results: $name",
      async ({ nextUrl, expectedSecondPath }) => {
        const fetch = buildFetchForPages(
          page([{ id: "a" }, { id: "b" }], nextUrl),
          page([{ id: "c" }]),
        );
        await expect(
          buildClient(fetch).getTaskSummaries(["a", "b", "c"]),
        ).resolves.toEqual([{ id: "a" }, { id: "b" }, { id: "c" }]);
        expect(fetch).toHaveBeenCalledTimes(2);
        expect(fetch.mock.calls[0][0]).toMatchObject({
          method: "post",
          path: SUMMARIES_PATH,
        });
        expect(fetch.mock.calls[1][0]).toMatchObject({
          method: "post",
          path: expectedSecondPath,
        });
      },
    );

    it("throws when the server responds non-OK", async () => {
      const fetch = vi
        .fn()
        .mockResolvedValue({ ok: false, statusText: "Bad Request" });
      await expect(buildClient(fetch).getTaskSummaries(["a"])).rejects.toThrow(
        "Bad Request",
      );
    });

    it("returns partial results when MAX_PAGES is exceeded", async () => {
      const fetch = vi
        .fn()
        .mockResolvedValue(
          page(
            [{ id: "x" }],
            `http://localhost:8000${SUMMARIES_PATH}?offset=1`,
          ),
        );
      const result = await buildClient(fetch).getTaskSummaries(["a"]);
      expect(fetch).toHaveBeenCalledTimes(50);
      expect(result.length).toBe(50);
    });
  });

  describe("task pins", () => {
    function buildClient(fetch: ReturnType<typeof vi.fn>) {
      const client = new PostHogAPIClient(
        "http://localhost:8000",
        async () => "token",
        async () => "token",
        123,
      );
      (
        client as unknown as {
          api: { baseUrl: string; fetcher: { fetch: typeof fetch } };
        }
      ).api = { baseUrl: "http://localhost:8000", fetcher: { fetch } };
      return client;
    }

    it("loads pinned task ids", async () => {
      const fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ task_ids: ["task-1", "task-2"] }),
      });

      await expect(buildClient(fetch).getPinnedTaskIds()).resolves.toEqual([
        "task-1",
        "task-2",
      ]);
      expect(fetch).toHaveBeenCalledWith(
        expect.objectContaining({
          method: "get",
          path: "/api/projects/123/tasks/pinned/",
        }),
      );
    });

    it("sets pin state idempotently", async () => {
      const fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ task_id: "task-1", pinned: true }),
      });

      await expect(
        buildClient(fetch).setTaskPinned("task-1", true),
      ).resolves.toBe(true);
      expect(fetch).toHaveBeenCalledWith(
        expect.objectContaining({
          method: "post",
          path: "/api/projects/123/tasks/task-1/pin/",
          overrides: { body: JSON.stringify({ pinned: true }) },
        }),
      );
    });
  });

  describe("getSignalReportArtefacts", () => {
    function makeClient(fetch: ReturnType<typeof vi.fn>) {
      const client = new PostHogAPIClient(
        "http://localhost:8000",
        async () => "token",
        async () => "token",
        123,
      );
      (
        client as unknown as {
          api: { baseUrl: string; fetcher: { fetch: typeof fetch } };
        }
      ).api = {
        baseUrl: "http://localhost:8000",
        fetcher: { fetch },
      };
      return client;
    }

    // One row per backend ArtefactType (products/signals/backend/models.py),
    // content shapes mirroring artefact_schemas.py / real API payloads.
    const ROWS = [
      {
        id: "a1",
        type: "video_segment",
        content: {
          session_id: "s1",
          start_time: "2026-06-01T00:00:00Z",
          end_time: "2026-06-01T00:01:00Z",
          distinct_id: "d1",
          content: "user rage-clicked the save button",
          distance_to_centroid: 0.1,
        },
        created_at: "2026-06-01T00:00:00Z",
      },
      {
        id: "a2",
        type: "safety_judgment",
        content: { choice: true, explanation: "No prompt injection found." },
        created_at: "2026-06-01T00:00:01Z",
        task_id: "t1",
      },
      {
        id: "a3",
        type: "actionability_judgment",
        content: {
          explanation: "Clear repro and code path.",
          actionability: "immediately_actionable",
          already_addressed: false,
        },
        created_at: "2026-06-01T00:00:02Z",
      },
      {
        id: "a4",
        type: "priority_judgment",
        content: { explanation: "Cosmetic race.", priority: "P3" },
        created_at: "2026-06-01T00:00:03Z",
      },
      {
        id: "a5",
        type: "signal_finding",
        content: {
          signal_id: "sig-1",
          relevant_code_paths: ["a.ts"],
          relevant_commit_hashes: { abc1234: "introduced the bug" },
          data_queried: "execute-sql",
          verified: true,
        },
        created_at: "2026-06-01T00:00:04Z",
      },
      {
        id: "a6",
        type: "repo_selection",
        content: { repository: "posthog/posthog", reason: "Caller provided." },
        created_at: "2026-06-01T00:00:05Z",
      },
      {
        id: "a7",
        type: "suggested_reviewers",
        content: [
          {
            github_login: "octocat",
            github_name: "Octo Cat",
            relevant_commits: [],
            user: null,
          },
        ],
        created_at: "2026-06-01T00:00:06Z",
      },
      {
        id: "a8",
        type: "dismissal",
        content: {
          reason: "already_fixed",
          note: "",
          user_id: 1,
          user_uuid: null,
        },
        created_at: "2026-06-01T00:00:07Z",
      },
      {
        id: "a9",
        type: "code_reference",
        content: {
          file_path: "src/a.ts",
          start_line: 1,
          end_line: 3,
          contents: "let x = 1",
          relevance_note: "origin",
        },
        created_at: "2026-06-01T00:00:08Z",
      },
      {
        id: "a11",
        type: "line_reference",
        content: {
          file_path: "src/a.ts",
          line: 2,
          note: "here",
          contents: "x++",
        },
        created_at: "2026-06-01T00:00:10Z",
      },
      {
        id: "a12",
        type: "commit",
        content: {
          repository: "posthog/posthog",
          branch: "main",
          commit_sha: "abc1234",
          message: "fix",
          note: null,
        },
        created_at: "2026-06-01T00:00:11Z",
      },
      {
        id: "a13",
        type: "task_run",
        content: { task_id: "t1", product: "tasks", type: "agent_run" },
        created_at: "2026-06-01T00:00:12Z",
        task_id: "t1",
      },
      {
        id: "a14",
        type: "note",
        content: { note: "Guinea-pig probe note." },
        created_at: "2026-06-01T00:00:13Z",
        task_id: "t1",
        created_by: null,
      },
    ];

    it("normalizes every backend artefact type without dropping rows", async () => {
      const fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ count: ROWS.length, results: ROWS }),
      });
      const client = makeClient(fetch);

      const { results, unavailableReason } =
        await client.getSignalReportArtefacts("r1");

      expect(unavailableReason).toBeUndefined();
      expect(results.map((a) => a.id)).toEqual(ROWS.map((r) => r.id));
      expect(results.map((a) => a.type)).toEqual(ROWS.map((r) => r.type));
      expect(results.every((a) => !a.degraded)).toBe(true);
    });

    it("keeps rows whose content does not match the type's shape as degraded previews", async () => {
      const rows = [
        // commit missing branch/sha — must not vanish
        {
          id: "bad1",
          type: "commit",
          content: { repository: "posthog/posthog", message: "where am I" },
          created_at: "2026-06-01T00:00:00Z",
          task_id: "t1",
        },
        // unknown future type with arbitrary object content
        {
          id: "bad2",
          type: "deploy_event",
          content: { reason: "rolled back v2" },
          created_at: "2026-06-01T00:00:01Z",
        },
        // empty content
        {
          id: "bad3",
          type: "note",
          content: {},
          created_at: "2026-06-01T00:00:02Z",
        },
      ];
      const fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ count: rows.length, results: rows }),
      });
      const client = makeClient(fetch);

      const { results } = await client.getSignalReportArtefacts("r1");

      expect(results.map((a) => a.id)).toEqual(["bad1", "bad2", "bad3"]);
      expect(results.every((a) => a.degraded)).toBe(true);
      expect(results[0].type).toBe("commit");
      expect((results[1].content as { content: string }).content).toBe(
        "rolled back v2",
      );
      // attribution survives the fallback path
      expect(results[0].task_id).toBe("t1");
    });
  });

  describe("updateSignalReportArtefact", () => {
    const ARTEFACT_PATH =
      "/api/projects/123/signals/reports/report-1/artefacts/art-1/";

    function makeClient(fetch: ReturnType<typeof vi.fn>) {
      const client = new PostHogAPIClient(
        "http://localhost:8000",
        async () => "token",
        async () => "token",
        123,
      );
      (
        client as unknown as {
          api: { baseUrl: string; fetcher: { fetch: typeof fetch } };
        }
      ).api = { baseUrl: "http://localhost:8000", fetcher: { fetch } };
      return client;
    }

    const OCTOCAT_REVIEWER = {
      github_login: "octocat",
      github_name: "The Octocat",
      relevant_commits: [],
      user: null,
    };

    it.each([
      {
        name: "PUTs the full-replacement content and returns the parsed artefact",
        input: [{ github_login: "octocat" }, { user_uuid: "uuid-1" }],
        responseContent: [OCTOCAT_REVIEWER],
      },
      {
        name: "sends an empty content array when clearing reviewers",
        input: [],
        responseContent: [],
      },
    ])("$name", async ({ input, responseContent }) => {
      const fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          id: "art-1",
          type: "suggested_reviewers",
          created_at: "2024-01-01T00:00:00Z",
          content: responseContent,
        }),
      });
      const client = makeClient(fetch);

      const result = await client.updateSignalReportArtefact(
        "report-1",
        "art-1",
        input,
      );

      expect(result.type).toBe("suggested_reviewers");
      expect(result.content).toEqual(responseContent);
      expect(fetch).toHaveBeenCalledWith(
        expect.objectContaining({
          method: "put",
          path: ARTEFACT_PATH,
          overrides: { body: JSON.stringify({ content: input }) },
        }),
      );
    });

    it("throws with the server message on a non-ok response", async () => {
      const fetch = vi.fn().mockResolvedValue({
        ok: false,
        text: async () =>
          '{"error":"Only suggested_reviewers artefacts may be modified via this endpoint."}',
      });
      const client = makeClient(fetch);

      await expect(
        client.updateSignalReportArtefact("report-1", "art-1", []),
      ).rejects.toThrow("Only suggested_reviewers");
    });

    it("throws when the response is not a suggested_reviewers artefact", async () => {
      const fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          id: "art-1",
          type: "dismissal",
          created_at: "2024-01-01T00:00:00Z",
          content: { reason: "noise", note: "" },
        }),
      });
      const client = makeClient(fetch);

      await expect(
        client.updateSignalReportArtefact("report-1", "art-1", []),
      ).rejects.toThrow("Unexpected response");
    });
  });

  describe("batched scout emissions", () => {
    const EMISSIONS_PATH =
      "/api/projects/123/signals/scout/runs/emissions/batch/";
    const REPORTS_PATH =
      "/api/projects/123/signals/scout/runs/emissions/reports/batch/";

    function buildClient(fetch: ReturnType<typeof vi.fn>) {
      const client = new PostHogAPIClient(
        "http://localhost:8000",
        async () => "token",
        async () => "token",
        123,
      );
      (
        client as unknown as {
          api: { baseUrl: string; fetcher: { fetch: typeof fetch } };
        }
      ).api = { baseUrl: "http://localhost:8000", fetcher: { fetch } };
      return client;
    }

    // Both batch methods share the same scoutBatchByRunIds helper, so their
    // empty short-circuit, request shape, and error path are exercised together.
    const methods = [
      ["batchScoutRunEmissions", EMISSIONS_PATH],
      ["batchScoutEmissionReports", REPORTS_PATH],
    ] as const;

    it.each(methods)(
      "%s short-circuits empty run ids without hitting the network",
      async (method) => {
        const fetch = vi.fn();
        const client = buildClient(fetch);
        await expect(client[method](123, [])).resolves.toEqual([]);
        expect(fetch).not.toHaveBeenCalled();
      },
    );

    it.each(methods)(
      "%s POSTs the run ids in one request and flattens the response",
      async (method, path) => {
        const rows = [
          { id: "e1", run_id: "r1" },
          { id: "e2", run_id: "r2" },
        ];
        const fetch = vi
          .fn()
          .mockResolvedValue({ ok: true, json: async () => rows });

        await expect(
          buildClient(fetch)[method](123, ["r1", "r2"]),
        ).resolves.toEqual(rows);
        expect(fetch).toHaveBeenCalledTimes(1);
        expect(fetch.mock.calls[0][0]).toMatchObject({ method: "post", path });
        expect(JSON.parse(fetch.mock.calls[0][0].overrides.body)).toEqual({
          run_ids: ["r1", "r2"],
        });
      },
    );

    it.each(methods)(
      "%s throws when the server responds non-OK",
      async (method) => {
        const fetch = vi
          .fn()
          .mockResolvedValue({ ok: false, statusText: "Bad Request" });
        await expect(buildClient(fetch)[method](123, ["r1"])).rejects.toThrow(
          "Bad Request",
        );
      },
    );

    it("unwraps a paginated reports payload", async () => {
      const links = [{ finding_id: "f1", source_id: "s1", report: null }];
      const fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ results: links }),
      });

      await expect(
        buildClient(fetch).batchScoutEmissionReports(123, ["r1"]),
      ).resolves.toEqual(links);
      expect(fetch.mock.calls[0][0]).toMatchObject({
        method: "post",
        path: REPORTS_PATH,
      });
    });

    it("splits >200 run ids into parallel chunks and concatenates them", async () => {
      const runIds = Array.from({ length: 450 }, (_, i) => `r${i}`);
      const fetch = vi.fn(async (req) => {
        const { run_ids } = JSON.parse(req.overrides.body) as {
          run_ids: string[];
        };
        return {
          ok: true,
          json: async () => run_ids.map((run_id) => ({ id: run_id, run_id })),
        };
      });

      const result = await buildClient(fetch).batchScoutRunEmissions(
        123,
        runIds,
      );
      // 450 ids → chunks of 200, 200, 50.
      expect(fetch).toHaveBeenCalledTimes(3);
      expect(result).toHaveLength(450);
      expect(result.map((row) => row.run_id)).toEqual(runIds);
    });
  });

  describe("getTaskRunSessionLogsResult", () => {
    function makeClient(fetch: ReturnType<typeof vi.fn>) {
      const client = new PostHogAPIClient(
        "http://localhost:8000",
        async () => "token",
        async () => "token",
        123,
      );
      (
        client as unknown as {
          api: { baseUrl: string; fetcher: { fetch: typeof fetch } };
        }
      ).api = { baseUrl: "http://localhost:8000", fetcher: { fetch } };
      return client;
    }

    function makeEntries(count: number, prefix: string) {
      return Array.from({ length: count }, (_, i) => ({
        type: "notification",
        timestamp: `2026-07-01T00:00:00.${String(i).padStart(3, "0")}Z`,
        notification: { method: `${prefix}-${i}` },
      }));
    }

    function page(
      entries: unknown[],
      hasMore: boolean,
      matchingCount?: number,
    ) {
      const headers = new Headers({ "X-Has-More": String(hasMore) });
      if (matchingCount !== undefined) {
        headers.set("X-Matching-Count", String(matchingCount));
      }
      return {
        ok: true,
        json: async () => entries,
        headers,
      };
    }

    function requestedParams(call: { url: URL }) {
      return Object.fromEntries(call.url.searchParams);
    }

    it.each([
      {
        name: "defaults to the server's max page size",
        options: undefined,
        expectedLimit: "5000",
      },
      {
        name: "clamps a larger total cap to the server's max page size",
        options: { limit: 100000 },
        expectedLimit: "5000",
      },
      {
        name: "requests fewer when the total cap is below the page size",
        options: { limit: 100 },
        expectedLimit: "100",
      },
    ])("$name", async ({ options, expectedLimit }) => {
      const fetch = vi.fn().mockResolvedValue(page(makeEntries(3, "a"), false));
      const client = makeClient(fetch);

      const result = (
        await client.getTaskRunSessionLogsResult("task-1", "run-1", options)
      ).entries;

      expect(result).toHaveLength(3);
      expect(fetch).toHaveBeenCalledTimes(1);
      expect(requestedParams(fetch.mock.calls[0][0])).toEqual({
        limit: expectedLimit,
      });
    });

    it("paginates until X-Has-More is false, advancing offset by entries actually returned", async () => {
      const fetch = vi
        .fn()
        .mockResolvedValueOnce(page(makeEntries(120, "a"), true))
        .mockResolvedValueOnce(page(makeEntries(80, "b"), true))
        .mockResolvedValueOnce(page(makeEntries(10, "c"), false));
      const client = makeClient(fetch);

      const result = (
        await client.getTaskRunSessionLogsResult("task-1", "run-1", {
          limit: 100000,
        })
      ).entries;

      expect(result).toHaveLength(210);
      expect(fetch).toHaveBeenCalledTimes(3);
      expect(requestedParams(fetch.mock.calls[1][0])).toEqual({
        limit: "5000",
        offset: "120",
      });
      expect(requestedParams(fetch.mock.calls[2][0])).toEqual({
        limit: "5000",
        offset: "200",
      });
    });

    it("stops at the requested total limit even when more pages remain", async () => {
      const fetch = vi
        .fn()
        .mockResolvedValueOnce(page(makeEntries(5000, "a"), true))
        .mockResolvedValueOnce(page(makeEntries(1000, "b"), true));
      const client = makeClient(fetch);

      const result = (
        await client.getTaskRunSessionLogsResult("task-1", "run-1", {
          limit: 6000,
        })
      ).entries;

      expect(result).toHaveLength(6000);
      expect(fetch).toHaveBeenCalledTimes(2);
      expect(requestedParams(fetch.mock.calls[1][0])).toEqual({
        limit: "1000",
        offset: "5000",
      });
    });

    it("forwards the after cursor on every page", async () => {
      const fetch = vi
        .fn()
        .mockResolvedValueOnce(page(makeEntries(10, "a"), true))
        .mockResolvedValueOnce(page(makeEntries(5, "b"), false));
      const client = makeClient(fetch);

      await client.getTaskRunSessionLogsResult("task-1", "run-1", {
        limit: 100000,
        after: "2026-07-01T00:00:00Z",
      });

      expect(requestedParams(fetch.mock.calls[0][0])).toEqual({
        limit: "5000",
        after: "2026-07-01T00:00:00Z",
      });
      expect(requestedParams(fetch.mock.calls[1][0])).toEqual({
        limit: "5000",
        offset: "10",
        after: "2026-07-01T00:00:00Z",
      });
    });

    it("fetches the newest entries when the log exceeds the requested cap", async () => {
      const fetch = vi
        .fn()
        .mockResolvedValueOnce(page(makeEntries(5000, "head"), true, 9000))
        .mockResolvedValueOnce(page(makeEntries(5000, "tail-a"), true, 9000))
        .mockResolvedValueOnce(page(makeEntries(1000, "tail-b"), false, 9000));
      const client = makeClient(fetch);

      const result = await client.getTaskRunSessionLogsResult(
        "task-1",
        "run-1",
        { limit: 6000 },
      );

      expect(result.complete).toBe(true);
      expect(result.truncatedHeadCount).toBe(3000);
      expect(result.entries).toHaveLength(6000);
      expect(
        (result.entries[0] as { notification: { method: string } }).notification
          .method,
      ).toBe("tail-a-0");
      expect(fetch).toHaveBeenCalledTimes(3);
      expect(requestedParams(fetch.mock.calls[1][0])).toEqual({
        limit: "5000",
        offset: "3000",
      });
      expect(requestedParams(fetch.mock.calls[2][0])).toEqual({
        limit: "1000",
        offset: "8000",
      });
    });

    it("does not refetch when the matching count equals the cap", async () => {
      const fetch = vi
        .fn()
        .mockResolvedValue(page(makeEntries(5000, "a"), false, 5000));
      const client = makeClient(fetch);

      const result = await client.getTaskRunSessionLogsResult(
        "task-1",
        "run-1",
        { limit: 5000 },
      );

      expect(result.complete).toBe(true);
      expect(result.truncatedHeadCount).toBe(0);
      expect(fetch).toHaveBeenCalledTimes(1);
    });

    it("retries a rejected page fetch once and keeps paginating", async () => {
      const fetch = vi
        .fn()
        .mockResolvedValueOnce(page(makeEntries(50, "a"), true))
        .mockRejectedValueOnce(new Error("socket hang up"))
        .mockResolvedValueOnce(page(makeEntries(10, "b"), false));
      const client = makeClient(fetch);

      const result = await client.getTaskRunSessionLogsResult(
        "task-1",
        "run-1",
        { limit: 100000 },
      );

      expect(result.complete).toBe(true);
      expect(result.entries).toHaveLength(60);
      expect(fetch).toHaveBeenCalledTimes(3);
      expect(
        (fetch.mock.calls[0][0] as { overrides: { signal: unknown } }).overrides
          .signal,
      ).toBeInstanceOf(AbortSignal);
    });

    it("reports a null matching count when the header is absent", async () => {
      const fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => makeEntries(10, "a"),
        headers: new Headers({ "X-Has-More": "true" }),
      });
      const client = makeClient(fetch);

      const result = await client.getTaskRunSessionLogsPage("task-1", "run-1", {
        limit: 10,
      });

      expect(result.matchingCount).toBeNull();
      expect(result.hasMore).toBe(true);
    });

    it("does not retry a definite client error", async () => {
      const fetch = vi.fn().mockRejectedValue(new ApiRequestError(404, "{}"));
      const client = makeClient(fetch);

      const result = await client.getTaskRunSessionLogsResult(
        "task-1",
        "run-1",
        { limit: 100000 },
      );

      expect(result.complete).toBe(false);
      expect(fetch).toHaveBeenCalledTimes(1);
    });

    it("gives up after a second rejection on the same page", async () => {
      const fetch = vi
        .fn()
        .mockResolvedValueOnce(page(makeEntries(50, "a"), true))
        .mockRejectedValue(new Error("socket hang up"));
      const client = makeClient(fetch);

      const result = await client.getTaskRunSessionLogsResult(
        "task-1",
        "run-1",
        { limit: 100000 },
      );

      expect(result.complete).toBe(false);
      expect(result.entries).toHaveLength(50);
      expect(fetch).toHaveBeenCalledTimes(3);
    });

    it("retries a page whose body read fails", async () => {
      const fetch = vi
        .fn()
        .mockResolvedValueOnce({
          ok: true,
          json: async () => {
            throw new Error("terminated");
          },
          headers: new Headers({ "X-Has-More": "true" }),
        })
        .mockResolvedValueOnce(page(makeEntries(10, "a"), false));
      const client = makeClient(fetch);

      const result = await client.getTaskRunSessionLogsResult(
        "task-1",
        "run-1",
        { limit: 100000 },
      );

      expect(result.complete).toBe(true);
      expect(result.entries).toHaveLength(10);
      expect(fetch).toHaveBeenCalledTimes(2);
    });

    it("aborts a page whose body stalls after the headers arrive", async () => {
      vi.useFakeTimers();
      try {
        const fetch = vi
          .fn()
          .mockImplementation((call: { overrides: { signal: AbortSignal } }) =>
            Promise.resolve({
              ok: true,
              json: () =>
                new Promise((_resolve, reject) => {
                  call.overrides.signal.addEventListener("abort", () =>
                    reject(call.overrides.signal.reason),
                  );
                }),
              headers: new Headers({ "X-Has-More": "false" }),
            }),
          );
        const client = makeClient(fetch);

        const pending = client.getTaskRunSessionLogsResult("task-1", "run-1", {
          limit: 100000,
        });
        // Once for the first attempt, once for its retry.
        await vi.advanceTimersByTimeAsync(SESSION_LOGS_PAGE_TIMEOUT_MS);
        await vi.advanceTimersByTimeAsync(SESSION_LOGS_PAGE_TIMEOUT_MS);

        const result = await pending;
        expect(result.complete).toBe(false);
        expect(result.entries).toHaveLength(0);
        expect(fetch).toHaveBeenCalledTimes(2);
      } finally {
        vi.useRealTimers();
      }
    });

    it("marks entries collected before a failed page as incomplete", async () => {
      const fetch = vi
        .fn()
        .mockResolvedValueOnce(page(makeEntries(50, "a"), true))
        .mockResolvedValueOnce({
          ok: false,
          status: 500,
          statusText: "Internal Server Error",
          headers: new Headers(),
        });
      const client = makeClient(fetch);

      const result = await client.getTaskRunSessionLogsResult(
        "task-1",
        "run-1",
        { limit: 100000 },
      );

      expect(result).toEqual({
        entries: expect.any(Array),
        complete: false,
        truncatedHeadCount: 0,
      });
      expect(result.entries).toHaveLength(50);
      expect(fetch).toHaveBeenCalledTimes(2);
    });

    it("treats a missing X-Has-More header as the final page", async () => {
      const fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => makeEntries(10, "a"),
        headers: new Headers(),
      });
      const client = makeClient(fetch);

      const result = (
        await client.getTaskRunSessionLogsResult("task-1", "run-1", {
          limit: 100000,
        })
      ).entries;

      expect(result).toHaveLength(10);
      expect(fetch).toHaveBeenCalledTimes(1);
    });

    it("stops on an empty page even if the server claims more", async () => {
      const fetch = vi.fn().mockResolvedValue(page([], true));
      const client = makeClient(fetch);

      const result = (
        await client.getTaskRunSessionLogsResult("task-1", "run-1", {
          limit: 100000,
        })
      ).entries;

      expect(result).toHaveLength(0);
      expect(fetch).toHaveBeenCalledTimes(1);
    });
  });

  describe("getMcpServerIconUrl", () => {
    function makeClient(fetch: ReturnType<typeof vi.fn>) {
      const client = new PostHogAPIClient(
        "http://localhost:8000",
        async () => "token",
        async () => "token",
        123,
      );
      (
        client as unknown as {
          api: { baseUrl: string; fetcher: { fetch: typeof fetch } };
        }
      ).api = { baseUrl: "http://localhost:8000", fetcher: { fetch } };
      return client;
    }

    it("requests the icon proxy and returns an object URL for the bytes", async () => {
      const fetch = vi
        .fn()
        .mockResolvedValue(
          new Response(new Blob(["png"], { type: "image/png" })),
        );
      const client = makeClient(fetch);

      const url = await client.getMcpServerIconUrl("linear.app", "dark");

      expect(url).toMatch(/^blob:/);
      expect(fetch.mock.calls[0][0].url.toString()).toBe(
        "http://localhost:8000/api/environments/123/mcp_servers/icon/?domain=linear.app&theme=dark",
      );
    });

    it("omits the theme param when none is given", async () => {
      const fetch = vi
        .fn()
        .mockResolvedValue(
          new Response(new Blob(["png"], { type: "image/png" })),
        );
      const client = makeClient(fetch);

      await client.getMcpServerIconUrl("linear.app");

      expect(fetch.mock.calls[0][0].url.toString()).toBe(
        "http://localhost:8000/api/environments/123/mcp_servers/icon/?domain=linear.app",
      );
    });

    it("treats the proxy's 404 as a definitive no-icon null, not a failure", async () => {
      const fetch = vi.fn().mockRejectedValue(new ApiRequestError(404, "{}"));
      const client = makeClient(fetch);

      await expect(
        client.getMcpServerIconUrl("no-logo.example"),
      ).resolves.toBeNull();
    });

    it("propagates non-404 failures so callers can retry", async () => {
      const fetch = vi.fn().mockRejectedValue(new ApiRequestError(500, "{}"));
      const client = makeClient(fetch);

      await expect(client.getMcpServerIconUrl("linear.app")).rejects.toThrow(
        "Failed request: [500]",
      );
    });
  });
});
