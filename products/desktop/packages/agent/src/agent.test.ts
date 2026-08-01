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
        headers: { Authorization: "Bearer token" },
      }),
    );
  });
});
