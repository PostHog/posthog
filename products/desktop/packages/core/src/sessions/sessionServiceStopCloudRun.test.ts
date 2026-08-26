import type { AgentSession } from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import { SessionService, type SessionServiceDeps } from "./sessionService";

function makeSession(overrides: Partial<AgentSession> = {}): AgentSession {
  return {
    taskRunId: "run-1",
    taskId: "task-1",
    taskTitle: "Test task",
    channel: "",
    events: [],
    startedAt: 1,
    status: "connected",
    isPromptPending: false,
    isCompacting: false,
    promptStartedAt: null,
    pendingPermissions: new Map(),
    pausedDurationMs: 0,
    messageQueue: [],
    optimisticItems: [],
    isCloud: true,
    cloudStatus: "in_progress",
    ...overrides,
  } as AgentSession;
}

function createHarness(
  session: AgentSession | undefined,
  stopMutate: ReturnType<typeof vi.fn>,
  latestRun: {
    id: string;
    environment: "local" | "cloud";
    status:
      | "not_started"
      | "queued"
      | "in_progress"
      | "completed"
      | "failed"
      | "cancelled";
  } | null = session
    ? {
        id: session.taskRunId,
        environment: session.isCloud ? "cloud" : "local",
        status: session.cloudStatus ?? "in_progress",
      }
    : { id: "run-1", environment: "cloud", status: "in_progress" },
) {
  const updateSession = vi.fn();
  const track = vi.fn();
  const deps = {
    store: {
      getSessionByTaskId: (taskId: string) =>
        session?.taskId === taskId ? session : undefined,
      updateSession,
    },
    log: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
    track,
    fetchAuthState: async () => ({ cloudRegion: "us", currentProjectId: 2 }),
    getAuthenticatedClient: async () => ({
      getTask: async () => ({ latest_run: latestRun }),
    }),
    trpc: {
      agent: {
        onSessionIdleKilled: {
          subscribe: () => ({ unsubscribe: vi.fn() }),
        },
      },
      cloudTask: {
        stop: { mutate: stopMutate },
      },
    },
  } as unknown as SessionServiceDeps;

  return { service: new SessionService(deps), updateSession, track };
}

describe("SessionService.stopCloudRun", () => {
  it("marks the session stopping and stops the run via the backend", async () => {
    const stopMutate = vi.fn().mockResolvedValue({ success: true });
    const { service, updateSession, track } = createHarness(
      makeSession(),
      stopMutate,
    );

    const result = await service.stopCloudRun("task-1");

    expect(result).toBe(true);
    expect(stopMutate).toHaveBeenCalledWith({
      taskId: "task-1",
      runId: "run-1",
    });
    expect(updateSession).toHaveBeenCalledWith(
      "run-1",
      expect.objectContaining({ stopRequested: true }),
    );
    expect(track).toHaveBeenCalledWith(
      "Task run stopped",
      expect.objectContaining({ task_id: "task-1", execution_type: "cloud" }),
    );
  });

  it("treats an already terminal cloud run as stopped", async () => {
    const stopMutate = vi.fn();
    const { service } = createHarness(
      makeSession({ cloudStatus: "cancelled" }),
      stopMutate,
    );

    const result = await service.stopCloudRun("task-1");

    expect(result).toBe(true);
    expect(stopMutate).not.toHaveBeenCalled();
  });

  it("repairs completion when the backend is terminal but the renderer is stale", async () => {
    const stopMutate = vi.fn().mockResolvedValue({ success: true });
    const { service } = createHarness(makeSession(), stopMutate, {
      id: "run-1",
      environment: "cloud",
      status: "cancelled",
    });

    const result = await service.stopCloudRun("task-1");

    expect(result).toBe(true);
    expect(stopMutate).toHaveBeenCalledWith({
      taskId: "task-1",
      runId: "run-1",
    });
  });

  it("does not call the backend for a local session", async () => {
    const stopMutate = vi.fn();
    const { service } = createHarness(
      makeSession({ isCloud: false }),
      stopMutate,
    );

    const result = await service.stopCloudRun("task-1");

    expect(result).toBe(true);
    expect(stopMutate).not.toHaveBeenCalled();
  });

  it("clears the stopping marker when the stop fails", async () => {
    const stopMutate = vi
      .fn()
      .mockResolvedValue({ success: false, error: "boom" });
    const { service, updateSession, track } = createHarness(
      makeSession({ isPromptPending: true, promptStartedAt: 123 }),
      stopMutate,
    );

    const result = await service.stopCloudRun("task-1");

    expect(result).toBe(false);
    expect(updateSession).toHaveBeenLastCalledWith("run-1", {
      stopRequested: false,
      isPromptPending: true,
      promptStartedAt: 123,
    });
    expect(track).not.toHaveBeenCalled();
  });

  it("stops a sidebar run that has no mounted session", async () => {
    const stopMutate = vi.fn().mockResolvedValue({ success: true });
    const { service, updateSession, track } = createHarness(
      undefined,
      stopMutate,
    );

    const result = await service.stopCloudRun("task-1", "run-1");

    expect(result).toBe(true);
    expect(stopMutate).toHaveBeenCalledWith({
      taskId: "task-1",
      runId: "run-1",
    });
    expect(updateSession).not.toHaveBeenCalled();
    expect(track).toHaveBeenCalledWith("Task run stopped", {
      task_id: "task-1",
      execution_type: "cloud",
    });
  });

  it("does not stop a newer run when the sidebar supplied a stale run id", async () => {
    const stopMutate = vi.fn().mockResolvedValue({ success: true });
    const { service } = createHarness(undefined, stopMutate, {
      id: "run-current",
      environment: "cloud",
      status: "queued",
    });

    const result = await service.stopCloudRun("task-1", "run-stale");

    expect(result).toBe(false);
    expect(stopMutate).not.toHaveBeenCalled();
  });
});
