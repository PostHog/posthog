import type { AgentSession } from "@posthog/shared";
import type { TaskRunStatus } from "@posthog/shared/domain-types";
import { describe, expect, it, vi } from "vitest";
import { SessionService, type SessionServiceDeps } from "./sessionService";

interface HydratableService {
  hydrateCloudTaskSessionFromLogs(
    taskId: string,
    taskRunId: string,
    logUrl?: string,
    taskDescription?: string,
    runStatus?: TaskRunStatus,
    runState?: Record<string, unknown>,
  ): Promise<unknown>;
}

function makeSession(): AgentSession {
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
  } as AgentSession;
}

function createHarness(
  options: {
    fetchAuthState?: () => Promise<unknown>;
    getTaskRunSessionLogsResult?: ReturnType<typeof vi.fn>;
  } = {},
) {
  const session = makeSession();
  const updateSession = vi.fn();
  const warn = vi.fn();
  const deps = {
    store: {
      getSessionByTaskId: (taskId: string) =>
        session.taskId === taskId ? session : undefined,
      getSessions: () => ({ [session.taskRunId]: session }),
      updateSession,
      clearTailOptimisticItems: vi.fn(),
    },
    log: { info: vi.fn(), warn, error: vi.fn(), debug: vi.fn() },
    fetchAuthState:
      options.fetchAuthState ??
      (async () => ({ cloudRegion: "us", currentProjectId: 2 })),
    createAuthenticatedClient: () => ({
      getTaskRunSessionLogsResult:
        options.getTaskRunSessionLogsResult ??
        vi.fn(async () => ({ complete: true, entries: [] })),
    }),
    trpc: {
      agent: {
        onSessionIdleKilled: { subscribe: () => ({ unsubscribe: vi.fn() }) },
      },
      logs: {
        readLocalLogs: { query: vi.fn(async () => null) },
        fetchS3Logs: { query: vi.fn(async () => null) },
      },
    },
  } as unknown as SessionServiceDeps;

  const service = new SessionService(deps) as unknown as HydratableService;
  return { service, updateSession, warn };
}

describe("SessionService cloud hydration flag", () => {
  it("sets isHydrating while a hydration is in flight and clears it after", async () => {
    const { service, updateSession } = createHarness();

    const hydration = service.hydrateCloudTaskSessionFromLogs(
      "task-1",
      "run-1",
      undefined,
      undefined,
      "in_progress",
    );

    expect(updateSession).toHaveBeenCalledWith("run-1", { isHydrating: true });
    expect(updateSession).not.toHaveBeenCalledWith("run-1", {
      isHydrating: false,
    });

    await hydration;

    expect(updateSession).toHaveBeenLastCalledWith("run-1", {
      isHydrating: false,
    });
  });

  it("clears isHydrating when the transcript fetch fails", async () => {
    const fetchResult = vi.fn().mockRejectedValue(new Error("fetch failed"));
    const { service, updateSession, warn } = createHarness({
      getTaskRunSessionLogsResult: fetchResult,
    });

    await service.hydrateCloudTaskSessionFromLogs(
      "task-1",
      "run-1",
      undefined,
      undefined,
      "completed",
    );

    expect(fetchResult).toHaveBeenCalled();
    expect(warn).toHaveBeenCalledWith(
      "Failed to hydrate cloud task session from logs",
      expect.objectContaining({ taskRunId: "run-1" }),
    );
    expect(updateSession).toHaveBeenLastCalledWith("run-1", {
      isHydrating: false,
    });
  });

  it("keeps isHydrating while a sibling hydration for the run is in flight", async () => {
    let releaseAuth: (value: unknown) => void = () => {};
    const gatedAuth = new Promise((resolve) => {
      releaseAuth = resolve;
    });
    const { service, updateSession } = createHarness({
      fetchAuthState: () => gatedAuth,
    });

    const singleHydration = service.hydrateCloudTaskSessionFromLogs(
      "task-1",
      "run-1",
      undefined,
      undefined,
      "in_progress",
    );
    const terminalHydration = service.hydrateCloudTaskSessionFromLogs(
      "task-1",
      "run-1",
      undefined,
      undefined,
      "completed",
    );

    await singleHydration;

    expect(updateSession).not.toHaveBeenCalledWith("run-1", {
      isHydrating: false,
    });

    releaseAuth({ status: "restoring" });
    await terminalHydration;

    expect(updateSession).toHaveBeenLastCalledWith("run-1", {
      isHydrating: false,
    });
  });
});
