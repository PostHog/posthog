import { beforeEach, describe, expect, it, vi } from "vitest";

const listTaskRunPeers = vi.fn();

vi.mock("../../../signed-commit-artefacts", () => ({
  createSandboxPosthogClient: () => ({ listTaskRunPeers }),
}));

import { listAgentsTool } from "./list-agents";

describe("list_agents tool", () => {
  const ctx = { cwd: "/repo", taskId: "task-1", taskRunId: "run-1" };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("lists each peer's run id verbatim with its sendability", async () => {
    listTaskRunPeers.mockResolvedValue([
      {
        run_id: "11111111-1111-4111-8111-111111111111",
        task_id: "t1",
        task_title: "fix billing",
        created_by_email: "dev@example.com",
        runtime: "pi",
        model: "claude-sonnet",
        repository: "org/repo",
        stage: "build",
        status: "in_progress",
        sendable: true,
        updated_at: "2026-08-11T00:00:00Z",
      },
      {
        run_id: "22222222-2222-4222-8222-222222222222",
        task_id: "t2",
        task_title: "migrate api",
        created_by_email: "dev@example.com",
        runtime: "pi",
        model: null,
        repository: null,
        stage: null,
        status: "queued",
        sendable: false,
        updated_at: null,
      },
    ]);

    const result = await listAgentsTool.handler(ctx, {});

    expect(result.isError).toBeUndefined();
    const text = result.content[0]?.text ?? "";
    // The run id is the address the model must copy into send_agent_message.
    expect(text).toContain("agent_run_id=11111111-1111-4111-8111-111111111111");
    expect(text).toContain('"fix billing"');
    expect(text).toContain("sendable");
    expect(text).toContain("not yet sendable");
  });

  it("explains the visibility scope when no peers exist", async () => {
    listTaskRunPeers.mockResolvedValue([]);

    const result = await listAgentsTool.handler(ctx, {});

    expect(result.isError).toBeUndefined();
    expect(result.content[0]?.text).toContain("No other active agent runs");
  });

  it("degrades a malformed response entry to a clean error instead of throwing", async () => {
    listTaskRunPeers.mockResolvedValue([null]);

    const result = await listAgentsTool.handler(ctx, {});

    expect(result.isError).toBe(true);
    expect(result.content[0]?.text).toContain("Listing agents failed");
  });

  it("surfaces backend errors (e.g. feature disabled) instead of an empty list", async () => {
    listTaskRunPeers.mockRejectedValue(
      new Error("Failed request: [403] Peer messaging is not enabled"),
    );

    const result = await listAgentsTool.handler(ctx, {});

    expect(result.isError).toBe(true);
    expect(result.content[0]?.text).toContain("Peer messaging is not enabled");
  });
});
