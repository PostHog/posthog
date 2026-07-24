import { describe, expect, it, vi } from "vitest";
import { ApiRequestError } from "./fetcher";
import { PostHogAPIClient } from "./posthog-client";

describe("PostHogAPIClient", () => {
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
    ).resolves.toEqual({ id: "run-123", environment: "cloud" });

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
    ).resolves.toEqual({ id: "task-123", latest_run: { id: "run-123" } });

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

  describe("agent model policy + catalog", () => {
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

    it("createAgentDraftRevisionFrom unwraps the { revision } envelope", async () => {
      // Regression: new_draft returns `{ revision, source_revision_id }`, not a
      // flat revision — returning the wrapper left `.id` undefined and broke the
      // follow-up PATCH (404 on /revisions/undefined/).
      const fetch = vi.fn().mockResolvedValue({
        json: async () => ({
          revision: { id: "draft-1", state: "draft" },
          source_revision_id: "rev-0",
        }),
      });
      const client = makeClient(fetch);

      const rev = await client.createAgentDraftRevisionFrom("app-1", "rev-0");

      expect(rev.id).toBe("draft-1");
      expect(fetch).toHaveBeenCalledWith(
        expect.objectContaining({
          method: "post",
          path: "/api/projects/123/agent_applications/app-1/revisions/new_draft/",
          overrides: {
            body: JSON.stringify({
              application_id: "app-1",
              source_revision_id: "rev-0",
            }),
          },
        }),
      );
    });

    it("updateAgentRevisionSpec PATCHes the revision with the full spec", async () => {
      const fetch = vi.fn().mockResolvedValue({
        json: async () => ({ id: "draft-1", state: "draft" }),
      });
      const client = makeClient(fetch);
      const spec = { models: { mode: "auto", level: "high" } };

      await client.updateAgentRevisionSpec(
        "agent-slug",
        "draft-1",
        spec as never,
      );

      expect(fetch).toHaveBeenCalledWith(
        expect.objectContaining({
          method: "patch",
          path: "/api/projects/123/agent_applications/agent-slug/revisions/draft-1/",
          overrides: { body: JSON.stringify({ spec }) },
        }),
      );
    });

    it("getAgentModelCatalog GETs the project-level models endpoint", async () => {
      const catalog = {
        models: [{ model: "anthropic/claude-haiku-4.5" }],
        levels: { low: ["anthropic/claude-haiku-4.5"] },
      };
      const fetch = vi.fn().mockResolvedValue({ json: async () => catalog });
      const client = makeClient(fetch);

      await expect(client.getAgentModelCatalog()).resolves.toEqual(catalog);
      expect(fetch).toHaveBeenCalledWith(
        expect.objectContaining({
          method: "get",
          path: "/api/projects/123/agent_applications/models/",
        }),
      );
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

  describe("getTaskRunSessionLogs", () => {
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

    function page(entries: unknown[], hasMore: boolean) {
      return {
        ok: true,
        json: async () => entries,
        headers: new Headers({ "X-Has-More": String(hasMore) }),
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

      const result = await client.getTaskRunSessionLogs(
        "task-1",
        "run-1",
        options,
      );

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

      const result = await client.getTaskRunSessionLogs("task-1", "run-1", {
        limit: 100000,
      });

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

      const result = await client.getTaskRunSessionLogs("task-1", "run-1", {
        limit: 6000,
      });

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

      await client.getTaskRunSessionLogs("task-1", "run-1", {
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

      expect(result).toEqual({ entries: expect.any(Array), complete: false });
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

      const result = await client.getTaskRunSessionLogs("task-1", "run-1", {
        limit: 100000,
      });

      expect(result).toHaveLength(10);
      expect(fetch).toHaveBeenCalledTimes(1);
    });

    it("stops on an empty page even if the server claims more", async () => {
      const fetch = vi.fn().mockResolvedValue(page([], true));
      const client = makeClient(fetch);

      const result = await client.getTaskRunSessionLogs("task-1", "run-1", {
        limit: 100000,
      });

      expect(result).toHaveLength(0);
      expect(fetch).toHaveBeenCalledTimes(1);
    });
  });

  describe("custom tool authoring", () => {
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

    // The shared fetcher throws `Failed request: [<status>] <json>` on non-2xx.
    const failWith = (status: number, body: unknown) =>
      new Error(`Failed request: [${status}] ${JSON.stringify(body)}`);

    describe("putRevisionTool", () => {
      it("returns an ok result with capabilities on 200", async () => {
        const fetch = vi.fn().mockResolvedValue({
          json: async () => ({
            ok: true,
            tool_id: "t1",
            capabilities: {
              secret_refs: ["API_KEY"],
              dynamic_secret_refs: false,
            },
          }),
        });
        const client = makeClient(fetch);

        await expect(
          client.putRevisionTool("agent", "rev-1", "t1", {
            description: "d",
            args_schema: {},
            source: "export default {}",
          }),
        ).resolves.toEqual({
          ok: true,
          tool_id: "t1",
          capabilities: {
            secret_refs: ["API_KEY"],
            dynamic_secret_refs: false,
          },
        });
        const call = fetch.mock.calls[0][0];
        expect(call.method).toBe("put");
        expect(call.path).toBe(
          "/api/projects/123/agent_applications/agent/revisions/rev-1/tools/t1/",
        );
      });

      it("returns a typed compile-failed result on 422 (not a throw)", async () => {
        const errors = [
          {
            kind: "parse_failed",
            message: "Unexpected token",
            line: 3,
            column: 5,
          },
        ];
        const fetch = vi.fn().mockRejectedValue(
          failWith(422, {
            error: "tool_compile_failed",
            tool_id: "t1",
            errors,
          }),
        );
        const client = makeClient(fetch);

        await expect(
          client.putRevisionTool("agent", "rev-1", "t1", {
            description: "d",
            args_schema: {},
            source: "bad(",
          }),
        ).resolves.toEqual({
          ok: false,
          error: "tool_compile_failed",
          tool_id: "t1",
          errors,
        });
      });

      it("rethrows non-422 failures (e.g. 409 sealed revision)", async () => {
        const fetch = vi
          .fn()
          .mockRejectedValue(failWith(409, { error: "revision_sealed" }));
        const client = makeClient(fetch);

        await expect(
          client.putRevisionTool("agent", "rev-1", "t1", {
            description: "d",
            args_schema: {},
            source: "x",
          }),
        ).rejects.toThrow("[409]");
      });
    });

    describe("deleteRevisionTool", () => {
      it("resolves on 200", async () => {
        const fetch = vi.fn().mockResolvedValue({ json: async () => ({}) });
        const client = makeClient(fetch);
        await expect(
          client.deleteRevisionTool("agent", "rev-1", "t1"),
        ).resolves.toBeUndefined();
        expect(fetch.mock.calls[0][0].method).toBe("delete");
      });

      it("treats a 404 (tool_not_found) as success", async () => {
        const fetch = vi
          .fn()
          .mockRejectedValue(failWith(404, { error: "tool_not_found" }));
        const client = makeClient(fetch);
        await expect(
          client.deleteRevisionTool("agent", "rev-1", "gone"),
        ).resolves.toBeUndefined();
      });

      it("rethrows other failures", async () => {
        const fetch = vi.fn().mockRejectedValue(failWith(500, "boom"));
        const client = makeClient(fetch);
        await expect(
          client.deleteRevisionTool("agent", "rev-1", "t1"),
        ).rejects.toThrow("[500]");
      });
    });

    describe("dryRunRevisionTool", () => {
      it("returns a completed envelope on a 200 success", async () => {
        const envelope = {
          ok: true,
          tool_id: "t1",
          result: { hello: "world" },
          duration_ms: 42,
        };
        const fetch = vi.fn().mockResolvedValue({ json: async () => envelope });
        const client = makeClient(fetch);

        await expect(
          client.dryRunRevisionTool("agent", "rev-1", "t1", { args: {} }),
        ).resolves.toEqual({ outcome: "completed", envelope });
      });

      it("returns a completed envelope for a 200 with ok:false (tool threw)", async () => {
        const envelope = {
          ok: false,
          tool_id: "t1",
          error: { code: "timeout", message: "wall clock exceeded" },
          duration_ms: 5000,
        };
        const fetch = vi.fn().mockResolvedValue({ json: async () => envelope });
        const client = makeClient(fetch);

        await expect(
          client.dryRunRevisionTool("agent", "rev-1", "t1", { args: {} }),
        ).resolves.toEqual({ outcome: "completed", envelope });
      });

      it("surfaces a 500 envelope as completed (infra failure carries error.code)", async () => {
        const envelope = {
          ok: false,
          tool_id: "t1",
          error: { code: "sandbox_acquire_failed", message: "no sandbox" },
          duration_ms: 12,
        };
        const fetch = vi.fn().mockRejectedValue(failWith(500, envelope));
        const client = makeClient(fetch);

        await expect(
          client.dryRunRevisionTool("agent", "rev-1", "t1", { args: {} }),
        ).resolves.toEqual({ outcome: "completed", envelope });
      });

      it("returns a throttled outcome on 429 (never throws, carries max_concurrent)", async () => {
        const fetch = vi
          .fn()
          .mockRejectedValue(
            failWith(429, { error: "dry_run_throttled", max_concurrent: 2 }),
          );
        const client = makeClient(fetch);

        await expect(
          client.dryRunRevisionTool("agent", "rev-1", "t1", { args: {} }),
        ).resolves.toEqual({ outcome: "throttled", max_concurrent: 2 });
      });

      it("throttles without a count when max_concurrent is absent", async () => {
        const fetch = vi
          .fn()
          .mockRejectedValue(failWith(429, { error: "dry_run_throttled" }));
        const client = makeClient(fetch);

        const result = await client.dryRunRevisionTool("agent", "rev-1", "t1", {
          args: {},
        });
        expect(result).toEqual({ outcome: "throttled" });
        expect(
          (result as { max_concurrent?: number }).max_concurrent,
        ).toBeUndefined();
      });

      it("returns an unavailable outcome on 503", async () => {
        const fetch = vi
          .fn()
          .mockRejectedValue(failWith(503, "not configured"));
        const client = makeClient(fetch);

        await expect(
          client.dryRunRevisionTool("agent", "rev-1", "t1", { args: {} }),
        ).resolves.toEqual({ outcome: "unavailable" });
      });

      it("passes mock_secrets through in the request body", async () => {
        const fetch = vi.fn().mockResolvedValue({
          json: async () => ({ ok: true, tool_id: "t1", duration_ms: 1 }),
        });
        const client = makeClient(fetch);

        await client.dryRunRevisionTool("agent", "rev-1", "t1", {
          args: { q: 1 },
          mock_secrets: { API_KEY: "placeholder" },
        });

        const body = JSON.parse(fetch.mock.calls[0][0].overrides.body);
        expect(body).toEqual({
          args: { q: 1 },
          mock_secrets: { API_KEY: "placeholder" },
        });
      });
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
