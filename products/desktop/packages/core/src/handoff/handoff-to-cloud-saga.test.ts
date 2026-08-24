import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  HandoffToCloudSaga,
  type HandoffToCloudSagaDeps,
} from "./handoff-to-cloud-saga";

function createDeps(
  overrides: Partial<HandoffToCloudSagaDeps> = {},
): HandoffToCloudSagaDeps {
  return {
    captureGitCheckpoint: vi.fn().mockResolvedValue({
      checkpointId: "checkpoint-1",
      checkpointRef: "refs/posthog-code-checkpoint/checkpoint-1",
    }),
    persistCheckpointToLog: vi.fn().mockResolvedValue(undefined),
    countLocalLogEntries: vi.fn().mockResolvedValue(7),
    resumeRunInCloud: vi.fn().mockResolvedValue(undefined),
    killSession: vi.fn().mockResolvedValue(undefined),
    updateWorkspaceMode: vi.fn(),
    onProgress: vi.fn(),
    ...overrides,
  } as unknown as HandoffToCloudSagaDeps;
}

describe("HandoffToCloudSaga", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("persists the fresh checkpoint, starts cloud, then kills the local session", async () => {
    const deps = createDeps();
    const order: string[] = [];

    vi.mocked(deps.persistCheckpointToLog).mockImplementation(async () => {
      order.push("checkpoint");
    });
    vi.mocked(deps.resumeRunInCloud).mockImplementation(async () => {
      order.push("resume");
    });
    vi.mocked(deps.killSession).mockImplementation(async () => {
      order.push("kill");
    });

    const saga = new HandoffToCloudSaga(deps);
    const result = await saga.run({
      taskId: "task-1",
      runId: "run-1",
      repoPath: "/repo/path",
      apiHost: "https://us.posthog.com",
      teamId: 1,
      localGitState: {
        head: "head-1",
        branch: "main",
        upstreamHead: "upstream-head-1",
        upstreamRemote: "origin",
        upstreamMergeRef: "refs/heads/main",
      },
    });

    expect(result.success).toBe(true);
    expect(order).toEqual(["checkpoint", "resume", "kill"]);
    expect(deps.countLocalLogEntries).toHaveBeenCalledWith("run-1");
    if (result.success) {
      expect(result.data.logEntryCount).toBe(7);
      expect(result.data.checkpointCaptured).toBe(true);
    }
  });

  it("reports logEntryCount of 0 when no local cache exists", async () => {
    const deps = createDeps({
      countLocalLogEntries: vi.fn().mockResolvedValue(0),
    });

    const saga = new HandoffToCloudSaga(deps);
    const result = await saga.run({
      taskId: "task-1",
      runId: "run-1",
      repoPath: "/repo/path",
      apiHost: "https://us.posthog.com",
      teamId: 1,
    });

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.logEntryCount).toBe(0);
    }
  });
});
