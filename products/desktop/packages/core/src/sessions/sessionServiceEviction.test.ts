import type { AgentSession } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MAX_CONNECTED_SESSIONS } from "./sessionEviction";
import {
  type ReconcileTaskConnectionParams,
  SessionService,
  type SessionServiceDeps,
} from "./sessionService";

function makeSession(
  taskId: string,
  startedAt: number,
  overrides: Partial<AgentSession> = {},
): AgentSession {
  return {
    taskRunId: `run-${taskId}`,
    taskId,
    taskTitle: taskId,
    channel: "",
    events: [],
    startedAt,
    status: "connected",
    isPromptPending: false,
    isCompacting: false,
    promptStartedAt: null,
    pendingPermissions: new Map(),
    pausedDurationMs: 0,
    messageQueue: [],
    optimisticItems: [],
    ...overrides,
  } as AgentSession;
}

function createHarness(seedSessions: AgentSession[]) {
  const sessions: Record<string, AgentSession> = {};
  for (const session of seedSessions) {
    sessions[session.taskRunId] = session;
  }
  const removeSession = vi.fn((taskRunId: string) => {
    delete sessions[taskRunId];
  });
  const cancelMutate = vi.fn().mockResolvedValue(undefined);
  const removePersistedConfigOptions = vi.fn();
  const removeAdapter = vi.fn();

  const store = {
    getSessions: () => sessions,
    getSessionByTaskId: (taskId: string) =>
      Object.values(sessions).find((s) => s.taskId === taskId),
    removeSession,
    updateSession: vi.fn(),
  };

  const log = {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  };

  const deps = {
    store,
    log,
    getPersistedConfigOptions: () => undefined,
    setPersistedConfigOptions: vi.fn(),
    removePersistedConfigOptions,
    adapterStore: {
      getAdapter: () => undefined,
      setAdapter: vi.fn(),
      removeAdapter,
    },
    trpc: {
      agent: {
        cancel: { mutate: cancelMutate },
        onSessionIdleKilled: {
          subscribe: () => ({ unsubscribe: vi.fn() }),
        },
      },
    },
  } as unknown as SessionServiceDeps;

  const service = new SessionService(deps);
  return {
    service,
    sessions,
    removeSession,
    cancelMutate,
    removePersistedConfigOptions,
    removeAdapter,
    log,
  };
}

function connectParamsFor(taskId: string) {
  return {
    task: { id: taskId, title: taskId, description: taskId } as Task,
    repoPath: "/repo",
  };
}

function seedIdleSessions(prefix = "idle", count = MAX_CONNECTED_SESSIONS) {
  return Array.from({ length: count }, (_, i) =>
    makeSession(`${prefix}-${i}`, i + 1),
  );
}

describe("SessionService idle session eviction", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("evicts the least recently used idle sessions beyond the budget", async () => {
    const seeds = seedIdleSessions();
    seeds.push(makeSession("active", 1000));
    const { service, removeSession } = createHarness(seeds);

    await service.connectToTask(connectParamsFor("active"));

    await vi.waitFor(() => {
      expect(removeSession).toHaveBeenCalledTimes(2);
    });
    expect(removeSession).toHaveBeenCalledWith("run-idle-0");
    expect(removeSession).toHaveBeenCalledWith("run-idle-1");
  });

  it("never evicts mounted or busy sessions", async () => {
    const seeds = Array.from({ length: MAX_CONNECTED_SESSIONS }, (_, i) =>
      makeSession(`idle-${i}`, i + 1, {
        isPromptPending: i === 1,
      }),
    );
    seeds.push(makeSession("active", 1000));
    const { service, removeSession } = createHarness(seeds);

    const unregister = service.registerMountedTask("idle-0");

    await service.connectToTask(connectParamsFor("active"));

    await vi.waitFor(() => {
      expect(removeSession).toHaveBeenCalledTimes(2);
    });
    expect(removeSession).not.toHaveBeenCalledWith("run-idle-0");
    expect(removeSession).not.toHaveBeenCalledWith("run-idle-1");
    expect(removeSession).toHaveBeenCalledWith("run-idle-2");
    expect(removeSession).toHaveBeenCalledWith("run-idle-3");
    unregister();
  });

  it("evicts nothing at or under the budget", async () => {
    const seeds = seedIdleSessions("idle", MAX_CONNECTED_SESSIONS - 2);
    seeds.push(makeSession("active", 1000));
    const { service, removeSession } = createHarness(seeds);

    await service.connectToTask(connectParamsFor("active"));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(removeSession).not.toHaveBeenCalled();
  });

  it("preserves the adapter and persisted config of evicted sessions", async () => {
    const seeds = seedIdleSessions();
    seeds.push(makeSession("active", 1000));
    const {
      service,
      removeSession,
      removePersistedConfigOptions,
      removeAdapter,
    } = createHarness(seeds);

    await service.connectToTask(connectParamsFor("active"));

    await vi.waitFor(() => {
      expect(removeSession).toHaveBeenCalledTimes(2);
    });
    expect(removePersistedConfigOptions).not.toHaveBeenCalled();
    expect(removeAdapter).not.toHaveBeenCalled();
  });

  it("drops the adapter and persisted config on a real disconnect", async () => {
    const { service, removePersistedConfigOptions, removeAdapter } =
      createHarness([makeSession("idle-0", 1)]);

    await service.disconnectFromTask("idle-0");

    expect(removePersistedConfigOptions).toHaveBeenCalledWith("run-idle-0");
    expect(removeAdapter).toHaveBeenCalledWith("run-idle-0");
  });

  it("bounds the budget when reconciling a cloud task", async () => {
    const seeds = seedIdleSessions();
    seeds.push(makeSession("cloud-active", 1000, { isCloud: true }));
    const { service, removeSession } = createHarness(seeds);

    service.reconcileTaskConnection({
      task: {
        id: "cloud-active",
        title: "cloud-active",
        description: "cloud-active",
      } as Task,
      session: undefined,
      repoPath: null,
      isCloud: true,
      isOnline: true,
      cloudAuth: { status: "loading" },
    } as ReconcileTaskConnectionParams);

    await vi.waitFor(() => {
      expect(removeSession).toHaveBeenCalledTimes(2);
    });
    expect(removeSession).toHaveBeenCalledWith("run-idle-0");
    expect(removeSession).not.toHaveBeenCalledWith("run-cloud-active");
  });

  it("evicts cloud sessions once their runs are terminal", async () => {
    const seeds = Array.from({ length: MAX_CONNECTED_SESSIONS }, (_, i) =>
      makeSession(`cloud-${i}`, i + 1, {
        isCloud: true,
        cloudStatus: "completed",
      }),
    );
    seeds.push(makeSession("active", 1000));
    const { service, removeSession } = createHarness(seeds);

    await service.connectToTask(connectParamsFor("active"));

    await vi.waitFor(() => {
      expect(removeSession).toHaveBeenCalledTimes(2);
    });
    expect(removeSession).toHaveBeenCalledWith("run-cloud-0");
    expect(removeSession).toHaveBeenCalledWith("run-cloud-1");
  });

  it("keeps a task protected while any mount remains", async () => {
    const seeds = seedIdleSessions();
    seeds.push(makeSession("active", 1000));
    const { service, removeSession } = createHarness(seeds);

    const unregisterFirst = service.registerMountedTask("idle-0");
    service.registerMountedTask("idle-0");
    unregisterFirst();

    await service.connectToTask(connectParamsFor("active"));

    await vi.waitFor(() => {
      expect(removeSession).toHaveBeenCalledTimes(2);
    });
    expect(removeSession).not.toHaveBeenCalledWith("run-idle-0");
  });

  it("frees a task for eviction after its last unmount", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    const seeds = seedIdleSessions();
    seeds.push(makeSession("active", 1000));
    const { service, removeSession } = createHarness(seeds);

    vi.setSystemTime(1_000);
    const unregisterFirst = service.registerMountedTask("idle-0");
    const unregisterSecond = service.registerMountedTask("idle-0");
    unregisterFirst();
    unregisterSecond();

    vi.setSystemTime(2_000);
    for (let i = 1; i < MAX_CONNECTED_SESSIONS; i++) {
      service.registerMountedTask(`idle-${i}`)();
    }

    vi.setSystemTime(3_000);
    await service.connectToTask(connectParamsFor("active"));

    await vi.waitFor(() => {
      expect(removeSession).toHaveBeenCalledWith("run-idle-0");
    });
  });

  it("keeps evicting after one teardown fails", async () => {
    const seeds = seedIdleSessions();
    seeds.push(makeSession("active", 1000));
    const { service, removeSession, log } = createHarness(seeds);
    removeSession.mockImplementationOnce(() => {
      throw new Error("dispose failed");
    });

    await service.connectToTask(connectParamsFor("active"));

    await vi.waitFor(() => {
      expect(removeSession).toHaveBeenCalledWith("run-idle-1");
    });
    expect(log.error).toHaveBeenCalledWith(
      "Failed to evict idle session",
      expect.objectContaining({ taskId: "idle-0" }),
    );
  });
});
