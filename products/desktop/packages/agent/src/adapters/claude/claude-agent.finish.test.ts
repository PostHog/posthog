import type { AgentSideConnection } from "@agentclientprotocol/sdk";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PostHogAPIConfig } from "../../types";

vi.mock("@anthropic-ai/claude-agent-sdk", () => ({
  query: vi.fn(),
}));

const mocks = vi.hoisted(() => ({
  updateTaskRun: vi.fn(),
  constructedConfigs: [] as unknown[],
}));

vi.mock("../../posthog-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../posthog-api")>();
  class FakePostHogAPIClient {
    updateTaskRun = mocks.updateTaskRun;
    constructor(config: unknown) {
      mocks.constructedConfigs.push(config);
    }
  }
  return { ...actual, PostHogAPIClient: FakePostHogAPIClient };
});

const { ClaudeAcpAgent } = await import("./claude-agent");

const API_CONFIG: PostHogAPIConfig = {
  apiUrl: "https://us.posthog.com",
  getApiKey: () => "key",
  projectId: 1,
};

type RequestFinish = (
  status: "completed" | "failed",
  message?: string,
) => Promise<void>;

function buildRequestFinish(
  posthogApiConfig: PostHogAPIConfig | undefined,
  taskId: string | undefined,
  taskRunId: string | undefined,
): RequestFinish | undefined {
  const client = {
    sessionUpdate: vi.fn().mockResolvedValue(undefined),
  } as unknown as AgentSideConnection;
  const agent = new ClaudeAcpAgent(client, { posthogApiConfig });
  return (
    agent as unknown as {
      buildRequestFinish(
        taskId: string | undefined,
        taskRunId: string | undefined,
      ): RequestFinish | undefined;
    }
  ).buildRequestFinish(taskId, taskRunId);
}

describe("ClaudeAcpAgent.buildRequestFinish", () => {
  beforeEach(() => {
    mocks.updateTaskRun.mockReset().mockResolvedValue({});
    mocks.constructedConfigs.length = 0;
  });

  it.each([
    {
      name: "no posthogApiConfig",
      config: undefined,
      taskId: "task-1",
      taskRunId: "run-1",
    },
    {
      name: "no taskId",
      config: API_CONFIG,
      taskId: undefined,
      taskRunId: "run-1",
    },
    {
      name: "no taskRunId",
      config: API_CONFIG,
      taskId: "task-1",
      taskRunId: undefined,
    },
  ])("is unavailable with $name", ({ config, taskId, taskRunId }) => {
    expect(buildRequestFinish(config, taskId, taskRunId)).toBeUndefined();
  });

  it("marks the run completed without an error_message", async () => {
    const requestFinish = buildRequestFinish(API_CONFIG, "task-1", "run-1");
    await requestFinish?.("completed");

    expect(mocks.constructedConfigs).toEqual([API_CONFIG]);
    expect(mocks.updateTaskRun).toHaveBeenCalledWith("task-1", "run-1", {
      status: "completed",
    });
  });

  it("marks the run failed with the message as error_message", async () => {
    const requestFinish = buildRequestFinish(API_CONFIG, "task-1", "run-1");
    await requestFinish?.("failed", "blocked on missing credentials");

    expect(mocks.updateTaskRun).toHaveBeenCalledWith("task-1", "run-1", {
      status: "failed",
      error_message: "blocked on missing credentials",
    });
  });

  it("omits error_message on a failed finish without a message", async () => {
    const requestFinish = buildRequestFinish(API_CONFIG, "task-1", "run-1");
    await requestFinish?.("failed");

    expect(mocks.updateTaskRun).toHaveBeenCalledWith("task-1", "run-1", {
      status: "failed",
    });
  });

  it("rethrows when the API update fails", async () => {
    mocks.updateTaskRun.mockRejectedValue(new Error("api down"));
    const requestFinish = buildRequestFinish(API_CONFIG, "task-1", "run-1");

    await expect(requestFinish?.("completed")).rejects.toThrow("api down");
  });
});
