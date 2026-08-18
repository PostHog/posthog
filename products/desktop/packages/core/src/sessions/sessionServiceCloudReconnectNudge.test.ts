import type { AgentSession } from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import { SessionService, type SessionServiceDeps } from "./sessionService";

function makeSession(taskId: string, runId: string): AgentSession {
  return {
    taskRunId: runId,
    taskId,
    taskTitle: taskId,
    channel: "",
    events: [
      {
        type: "acp_message",
        ts: 1,
        message: { jsonrpc: "2.0", method: "noop" },
      },
    ],
    processedLineCount: 1,
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
    isTaskAuthor: true,
    adapter: "claude",
    cloudStatus: "in_progress",
  };
}

function createHarness() {
  const sessions: Record<string, AgentSession> = {};
  const store = {
    getSessions: () => sessions,
    getSessionByTaskId: (taskId: string) =>
      Object.values(sessions).find((s) => s.taskId === taskId),
    setSession: vi.fn((session: AgentSession) => {
      sessions[session.taskRunId] = session;
    }),
    updateSession: vi.fn(
      (taskRunId: string, updates: Partial<AgentSession>) => {
        const session = sessions[taskRunId];
        if (session) Object.assign(session, updates);
      },
    ),
    updateCloudStatus: vi.fn(),
  };
  const reconnectMutate = vi.fn().mockResolvedValue(undefined);

  const deps = {
    store,
    log: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
    getPersistedConfigOptions: () => undefined,
    setPersistedConfigOptions: vi.fn(),
    removePersistedConfigOptions: vi.fn(),
    adapterStore: {
      getAdapter: () => undefined,
      setAdapter: vi.fn(),
      removeAdapter: vi.fn(),
    },
    trpc: {
      agent: {
        getPreviewConfigOptions: {
          query: vi.fn().mockRejectedValue(new Error("not in test")),
        },
        onSessionIdleKilled: {
          subscribe: () => ({ unsubscribe: vi.fn() }),
        },
      },
      cloudTask: {
        onUpdate: {
          subscribe: vi.fn(() => ({ unsubscribe: vi.fn() })),
        },
        watch: { mutate: vi.fn().mockResolvedValue(undefined) },
        unwatch: { mutate: vi.fn().mockResolvedValue(undefined) },
        reconnectIfDisconnected: { mutate: reconnectMutate },
      },
    },
  } as unknown as SessionServiceDeps;

  const service = new SessionService(deps);
  return { service, sessions, reconnectMutate };
}

function watchTask(service: SessionService, taskId: string, runId: string) {
  service.watchCloudTask(
    taskId,
    runId,
    "https://us.posthog.com",
    2,
    undefined,
    undefined,
    undefined,
    "claude",
    undefined,
    undefined,
    undefined,
    "in_progress",
  );
}

describe("SessionService reconnectDisconnectedCloudStreams", () => {
  it("nudges every actively watched cloud stream", () => {
    const { service, sessions, reconnectMutate } = createHarness();
    sessions["run-1"] = makeSession("task-1", "run-1");
    sessions["run-2"] = makeSession("task-2", "run-2");
    watchTask(service, "task-1", "run-1");
    watchTask(service, "task-2", "run-2");

    service.reconnectDisconnectedCloudStreams();

    expect(reconnectMutate).toHaveBeenCalledTimes(2);
    expect(reconnectMutate).toHaveBeenCalledWith({
      taskId: "task-1",
      runId: "run-1",
    });
    expect(reconnectMutate).toHaveBeenCalledWith({
      taskId: "task-2",
      runId: "run-2",
    });
  });

  it("skips sessions already in the error state", () => {
    const { service, sessions, reconnectMutate } = createHarness();
    sessions["run-1"] = makeSession("task-1", "run-1");
    sessions["run-2"] = makeSession("task-2", "run-2");
    watchTask(service, "task-1", "run-1");
    watchTask(service, "task-2", "run-2");
    sessions["run-2"].status = "error";

    service.reconnectDisconnectedCloudStreams();

    expect(reconnectMutate).toHaveBeenCalledTimes(1);
    expect(reconnectMutate).toHaveBeenCalledWith({
      taskId: "task-1",
      runId: "run-1",
    });
  });

  it("does nothing without active watchers", () => {
    const { service, reconnectMutate } = createHarness();
    service.reconnectDisconnectedCloudStreams();
    expect(reconnectMutate).not.toHaveBeenCalled();
  });
});
