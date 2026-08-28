import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AcpConnectionConfig } from "./adapters/acp-connection";

const createAcpConnectionMock = vi.hoisted(() =>
  vi.fn(() => ({ cleanup: vi.fn() }) as never),
);

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

vi.mock("./adapters/acp-connection", () => {
  return {
    createAcpConnection: createAcpConnectionMock,
  };
});

import { Agent } from "./agent";

describe("Agent", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchMock.mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({
        data: [{ id: "gpt-5.5", owned_by: "openai" }],
      }),
    });
  });

  it("passes reasoning effort through to local Codex options", async () => {
    const agent = new Agent({
      posthog: {
        apiUrl: "https://us.posthog.com",
        getApiKey: vi.fn().mockResolvedValue("token"),
        projectId: 1,
      },
      skipLogPersistence: true,
    });

    await agent.run("task-1", "run-1", {
      adapter: "codex",
      model: "gpt-5.5",
      reasoningEffort: "xhigh",
      repositoryPath: "/tmp/repo",
    });

    expect(createAcpConnectionMock).toHaveBeenCalledTimes(1);
    const [[config]] = createAcpConnectionMock.mock.calls as unknown as [
      [AcpConnectionConfig],
    ];
    expect(config.codexOptions).toEqual(
      expect.objectContaining({
        model: "gpt-5.5",
        reasoningEffort: "xhigh",
      }),
    );
    expect(config.codexModels).toEqual([
      expect.objectContaining({ id: "gpt-5.5", allowed: true }),
    ]);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        headers: {
          Authorization: "Bearer token",
          "X-PostHog-Project-Id": "1",
        },
      }),
    );
  });

  it("uses machine authentication for a ChatGPT subscription", async () => {
    const agent = new Agent({ skipLogPersistence: true });

    await agent.run("task-1", "run-1", {
      adapter: "codex",
      codexModelAccess: "own-subscription",
      repositoryPath: "/tmp/repo",
    });

    const [[config]] = createAcpConnectionMock.mock.calls as unknown as [
      [AcpConnectionConfig],
    ];
    expect(config.codexOptions).toEqual(
      expect.objectContaining({ useMachineAuth: true }),
    );
  });

  it("stops before starting Codex without authentication", async () => {
    const agent = new Agent({ skipLogPersistence: true });

    await expect(
      agent.run("task-1", "run-1", {
        adapter: "codex",
        codexModelAccess: "posthog-gateway",
      }),
    ).rejects.toThrow("Codex authentication is not ready");
    expect(createAcpConnectionMock).not.toHaveBeenCalled();
  });

  it("scopes local Claude sessions to the selected project", async () => {
    const agent = new Agent({
      posthog: {
        apiUrl: "https://us.posthog.com",
        getApiKey: vi.fn().mockResolvedValue("token"),
        projectId: 7,
      },
      skipLogPersistence: true,
    });

    await agent.run("task-1", "run-1", {
      adapter: "claude",
      repositoryPath: "/tmp/repo",
    });

    expect(createAcpConnectionMock).toHaveBeenCalledTimes(1);
    const [[config]] = createAcpConnectionMock.mock.calls as unknown as [
      [AcpConnectionConfig],
    ];
    expect(config.claudeGatewayEnv?.posthogProjectId).toBe("7");
  });

  it("adds task attribution to local Claude gateway headers", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: vi.fn().mockResolvedValue({
        origin_product: "posthog_code",
        repositories: ["org/repo"],
      }),
    });
    const agent = new Agent({
      posthog: {
        apiUrl: "https://us.posthog.com",
        getApiKey: vi.fn().mockResolvedValue("token"),
        projectId: 7,
      },
      skipLogPersistence: true,
    });

    await agent.run("task-1", "run-1", { adapter: "claude" });

    const [[config]] = createAcpConnectionMock.mock.calls as unknown as [
      [AcpConnectionConfig],
    ];
    expect(config.claudeGatewayEnv?.anthropicCustomHeaders).toContain(
      "x-posthog-property-task_id: task-1",
    );
    expect(config.claudeGatewayEnv?.anthropicCustomHeaders).toContain(
      'x-posthog-property-task_repositories: ["org/repo"]',
    );
    expect(config.claudeGatewayEnv?.anthropicCustomHeaders).toContain(
      "x-posthog-property-task_execution_environment: local",
    );
  });

  it("asserts the person's node so the gateway's per-user spend limit applies", async () => {
    fetchMock.mockImplementation((url: unknown) =>
      Promise.resolve({
        ok: true,
        json: vi
          .fn()
          .mockResolvedValue(
            String(url).includes("/api/users/@me/")
              ? { distinct_id: "user-distinct-1" }
              : { origin_product: "posthog_code" },
          ),
      }),
    );
    const agent = new Agent({
      posthog: {
        apiUrl: "https://us.posthog.com",
        getApiKey: vi.fn().mockResolvedValue("token"),
        projectId: 7,
      },
      skipLogPersistence: true,
    });

    await agent.run("task-1", "run-1", { adapter: "claude" });

    const [[config]] = createAcpConnectionMock.mock.calls as unknown as [
      [AcpConnectionConfig],
    ];
    expect(config.claudeGatewayEnv?.anthropicCustomHeaders).toContain(
      "X-PostHog-User: user-distinct-1",
    );
  });

  it("does not fetch or add task attribution for preview sessions", async () => {
    const agent = new Agent({
      posthog: {
        apiUrl: "https://us.posthog.com",
        getApiKey: vi.fn().mockResolvedValue("token"),
        projectId: 7,
      },
      skipLogPersistence: true,
    });

    await agent.run("__preview__", "run-1", { adapter: "claude" });

    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/tasks/__preview__/"),
      expect.anything(),
    );
    const [[config]] = createAcpConnectionMock.mock.calls as unknown as [
      [AcpConnectionConfig],
    ];
    expect(config.claudeGatewayEnv?.anthropicCustomHeaders).toBe("");
  });
});
