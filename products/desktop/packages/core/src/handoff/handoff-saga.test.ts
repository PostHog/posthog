import type { GitHandoffCheckpoint } from "@posthog/shared";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  type HandoffResumeState,
  HandoffSaga,
  type HandoffSagaDeps,
  type HandoffSagaInput,
} from "./handoff-saga";

const DEFAULT_LOCAL_GIT_STATE = {
  head: "abc123",
  branch: "feature/handoff",
  upstreamHead: null,
  upstreamRemote: "origin",
  upstreamMergeRef: "refs/heads/feature/handoff",
};

function createInput(
  overrides: Partial<HandoffSagaInput> = {},
): HandoffSagaInput {
  return {
    taskId: "task-1",
    runId: "run-1",
    repoPath: "/repo",
    apiHost: "https://us.posthog.com",
    teamId: 2,
    ...overrides,
  };
}

function createCheckpoint(
  overrides: Partial<GitHandoffCheckpoint> = {},
): GitHandoffCheckpoint {
  return {
    checkpointId: "checkpoint-1",
    commit: "checkpointcommit123",
    checkpointRef: "refs/posthog-code-checkpoint/checkpoint-1",
    headRef: "refs/posthog-code-handoff/head/checkpoint-1",
    head: "def456",
    branch: "feature/handoff",
    indexTree: "index123",
    worktreeTree: "worktree123",
    timestamp: "2026-04-07T00:00:00Z",
    upstreamRemote: "origin",
    upstreamMergeRef: "refs/heads/feature/handoff",
    remoteUrl: "git@github.com:PostHog/code.git",
    ...overrides,
  };
}

function createResumeState(
  overrides: Partial<HandoffResumeState> = {},
): HandoffResumeState {
  return {
    conversation: [],
    latestGitCheckpoint: null,
    ...overrides,
  };
}

function createDeps(overrides: Partial<HandoffSagaDeps> = {}): HandoffSagaDeps {
  return {
    markRunEnvironmentLocal: vi.fn().mockResolvedValue(undefined),
    fetchResumeState: vi.fn().mockResolvedValue({
      resumeState: createResumeState(),
      cloudLogUrl: "https://logs.example.com/run-1.ndjson",
    }),
    formatConversation: vi.fn().mockReturnValue("conversation summary"),
    applyGitCheckpoint: vi.fn().mockResolvedValue(undefined),
    updateWorkspaceMode: vi.fn(),
    attachWorkspaceToFolder: vi.fn().mockReturnValue({ revert: vi.fn() }),
    reconnectSession: vi.fn().mockResolvedValue({ sessionId: "session-1" }),
    closeCloudRun: vi.fn().mockResolvedValue(undefined),
    seedLocalLogs: vi.fn().mockResolvedValue(undefined),
    killSession: vi.fn().mockResolvedValue(undefined),
    setPendingContext: vi.fn(),
    onProgress: vi.fn(),
    ...overrides,
  };
}

function getProgressSteps(deps: HandoffSagaDeps): string[] {
  return (deps.onProgress as ReturnType<typeof vi.fn>).mock.calls.map(
    (call: unknown[]) => call[0] as string,
  );
}

async function runSaga(
  overrides: {
    input?: Partial<HandoffSagaInput>;
    deps?: Partial<HandoffSagaDeps>;
    resumeState?: Partial<HandoffResumeState>;
    cloudLogUrl?: string | null;
  } = {},
) {
  const deps = createDeps({
    fetchResumeState: vi.fn().mockResolvedValue({
      resumeState: createResumeState(overrides.resumeState),
      cloudLogUrl:
        overrides.cloudLogUrl === undefined
          ? "https://logs.example.com/run-1.ndjson"
          : overrides.cloudLogUrl,
    }),
    ...overrides.deps,
  });
  const saga = new HandoffSaga(deps);
  const result = await saga.run(createInput(overrides.input));
  return { deps, result };
}

describe("HandoffSaga", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("completes happy path with checkpoint", async () => {
    const checkpoint = createCheckpoint();
    const { result } = await runSaga({
      resumeState: {
        conversation: [
          { role: "user", content: [{ type: "text", text: "hello" }] },
        ],
        latestGitCheckpoint: checkpoint,
      },
    });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.sessionId).toBe("session-1");
    expect(result.data.checkpointApplied).toBe(true);
    expect(result.data.conversationTurns).toBe(1);
  });

  it("closes cloud run before fetching logs", async () => {
    const { deps } = await runSaga();

    expect(deps.closeCloudRun).toHaveBeenCalledWith(
      "task-1",
      "run-1",
      "https://us.posthog.com",
      2,
      undefined,
    );
    const closeOrder = (deps.closeCloudRun as ReturnType<typeof vi.fn>).mock
      .invocationCallOrder[0];
    const fetchOrder = (deps.fetchResumeState as ReturnType<typeof vi.fn>).mock
      .invocationCallOrder[0];
    expect(closeOrder).toBeLessThan(fetchOrder);
  });

  it("marks the run environment local before rebuilding state", async () => {
    const { deps } = await runSaga();

    expect(deps.markRunEnvironmentLocal).toHaveBeenCalledWith(
      "task-1",
      "run-1",
    );
    const envOrder = (deps.markRunEnvironmentLocal as ReturnType<typeof vi.fn>)
      .mock.invocationCallOrder[0];
    const fetchOrder = (deps.fetchResumeState as ReturnType<typeof vi.fn>).mock
      .invocationCallOrder[0];
    expect(envOrder).toBeLessThan(fetchOrder);
  });

  it("skips checkpoint apply when no checkpoint is present", async () => {
    const { deps, result } = await runSaga();

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(result.data.checkpointApplied).toBe(false);
    expect(deps.applyGitCheckpoint).not.toHaveBeenCalled();
  });

  it("seeds local logs when cloudLogUrl is present", async () => {
    const { deps } = await runSaga();

    expect(deps.seedLocalLogs).toHaveBeenCalledWith(
      "run-1",
      "https://logs.example.com/run-1.ndjson",
    );
  });

  it("skips seeding logs when cloudLogUrl is falsy", async () => {
    const { deps } = await runSaga({ cloudLogUrl: null });

    expect(deps.seedLocalLogs).not.toHaveBeenCalled();
  });

  it("sets pending context with handoff summary", async () => {
    const { deps } = await runSaga({
      deps: {
        formatConversation: vi.fn().mockReturnValue("User said hello"),
      },
      resumeState: {
        conversation: [
          { role: "user", content: [{ type: "text", text: "hello" }] },
        ],
      },
    });

    expect(deps.setPendingContext).toHaveBeenCalledWith(
      "run-1",
      expect.stringContaining("resuming a previous conversation"),
    );
    expect(deps.setPendingContext).toHaveBeenCalledWith(
      "run-1",
      expect.stringContaining("could not be restored"),
    );
  });

  it("context mentions files restored when checkpoint applied", async () => {
    const { deps } = await runSaga({
      resumeState: {
        latestGitCheckpoint: createCheckpoint(),
      },
    });

    expect(deps.setPendingContext).toHaveBeenCalledWith(
      "run-1",
      expect.stringContaining("restored from the cloud session checkpoint"),
    );
  });

  it("passes sessionId and adapter through to reconnectSession", async () => {
    const { deps } = await runSaga({
      input: { sessionId: "ses-abc", adapter: "codex" },
    });

    expect(deps.reconnectSession).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "ses-abc",
        adapter: "codex",
      }),
    );
  });

  it("emits progress events in order", async () => {
    const { deps } = await runSaga({
      resumeState: {
        latestGitCheckpoint: createCheckpoint(),
      },
    });

    expect(getProgressSteps(deps)).toEqual([
      "fetching_logs",
      "applying_git_checkpoint",
      "spawning_agent",
      "complete",
    ]);
  });

  describe("rollbacks", () => {
    it("reverts workspace attachment when spawn_agent fails", async () => {
      const revert = vi.fn();
      const { deps, result } = await runSaga({
        deps: {
          attachWorkspaceToFolder: vi.fn().mockReturnValue({ revert }),
          reconnectSession: vi
            .fn()
            .mockRejectedValue(new Error("spawn failed")),
        },
      });

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.failedStep).toBe("spawn_agent");
      expect(deps.attachWorkspaceToFolder).toHaveBeenCalledWith(
        "task-1",
        "/repo",
      );
      expect(revert).toHaveBeenCalledTimes(1);
    });

    it("kills session on rollback if spawn partially succeeded", async () => {
      const { result } = await runSaga({
        deps: {
          reconnectSession: vi.fn().mockResolvedValue(null),
        },
      });

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.failedStep).toBe("spawn_agent");
    });

    it("fails at fetch_and_rebuild without touching workspace state", async () => {
      const deps = createDeps({
        fetchResumeState: vi.fn().mockRejectedValue(new Error("API down")),
      });
      const saga = new HandoffSaga(deps);
      const result = await saga.run(createInput());

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.failedStep).toBe("fetch_and_rebuild");
      expect(deps.attachWorkspaceToFolder).not.toHaveBeenCalled();
      expect(deps.reconnectSession).not.toHaveBeenCalled();
    });
  });

  it("applies git checkpoint with local git state during handoff", async () => {
    const { deps, result } = await runSaga({
      input: { localGitState: DEFAULT_LOCAL_GIT_STATE },
      resumeState: {
        latestGitCheckpoint: createCheckpoint(),
      },
    });

    expect(result.success).toBe(true);
    if (!result.success) return;
    expect(deps.applyGitCheckpoint).toHaveBeenCalledTimes(1);
    expect(deps.applyGitCheckpoint).toHaveBeenCalledWith(
      expect.any(Object),
      "/repo",
      "task-1",
      "run-1",
      DEFAULT_LOCAL_GIT_STATE,
    );
  });
});
