import { beforeEach, describe, expect, it, vi } from "vitest";
import { PostHogAPIClient } from "./posthog-api";

const mockFetch = vi.fn();

vi.stubGlobal("fetch", mockFetch);

describe("PostHogAPIClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
      "includes message_id and text_parts when provided",
      ["part one", "final answer"],
      "msg-1",
      {
        text: "final answer",
        text_parts: ["part one", "final answer"],
        message_id: "msg-1",
      },
    ],
    [
      "omits optional fields when unknown",
      undefined,
      undefined,
      { text: "final answer" },
    ],
  ])(
    "relay_message body %s",
    async (_label, textParts, messageId, expectedBody) => {
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

  it("returns only the artifacts created by the current upload request", async () => {
    const client = new PostHogAPIClient({
      apiUrl: "https://app.posthog.com",
      getApiKey: vi.fn().mockResolvedValue("token"),
      projectId: 1,
    });

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: vi.fn().mockResolvedValue({
        artifacts: [
          { storage_path: "gs://bucket/existing.tar.gz", name: "existing" },
          { storage_path: "gs://bucket/new-1.pack", name: "new-1" },
          { storage_path: "gs://bucket/new-2.index", name: "new-2" },
        ],
      }),
    });

    const artifacts = await client.uploadTaskArtifacts("task-1", "run-1", [
      { name: "new-1", type: "artifact", content: "AAA" },
      { name: "new-2", type: "artifact", content: "BBB" },
    ]);

    expect(artifacts).toEqual([
      { storage_path: "gs://bucket/new-1.pack", name: "new-1" },
      { storage_path: "gs://bucket/new-2.index", name: "new-2" },
    ]);
  });
});
