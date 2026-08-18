import type { AgentSession } from "@posthog/shared";
import type { CloudTaskUpdatePayload } from "@posthog/shared/domain-types";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SessionService, type SessionServiceDeps } from "./sessionService";

const TASK_ID = "task-1";
const RUN_ID = "run-1";

type SubscriptionHandlers = {
  onData: (data: CloudTaskUpdatePayload) => void;
  onError?: (err: unknown) => void;
};

function makeSession(): AgentSession {
  return {
    taskRunId: RUN_ID,
    taskId: TASK_ID,
    taskTitle: "Test task",
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
  const sessions: Record<string, AgentSession> = { [RUN_ID]: makeSession() };
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
    appendEvents: vi.fn(),
    clearTailOptimisticItems: vi.fn(),
    clearMessageQueue: vi.fn(),
  };

  const subscriptions: Array<{
    handlers: SubscriptionHandlers;
    unsubscribe: ReturnType<typeof vi.fn>;
  }> = [];
  const subscribe = vi.fn((_input: unknown, handlers: SubscriptionHandlers) => {
    const unsubscribe = vi.fn();
    subscriptions.push({ handlers, unsubscribe });
    return { unsubscribe };
  });
  const watchMutate = vi.fn().mockResolvedValue(undefined);

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
        onUpdate: { subscribe },
        watch: { mutate: watchMutate },
        unwatch: { mutate: vi.fn().mockResolvedValue(undefined) },
      },
    },
  } as unknown as SessionServiceDeps;

  const service = new SessionService(deps);
  return { service, sessions, subscriptions, watchMutate };
}

function watchTask(service: SessionService) {
  service.watchCloudTask(
    TASK_ID,
    RUN_ID,
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

function heartbeat(): CloudTaskUpdatePayload {
  return { taskId: TASK_ID, runId: RUN_ID, kind: "heartbeat" };
}

describe("SessionService cloud stream watchdog", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("resyncs a stream that went silent past the threshold", async () => {
    const { service, subscriptions, watchMutate } = createHarness();
    watchTask(service);
    await vi.advanceTimersByTimeAsync(0);
    expect(subscriptions).toHaveLength(1);
    expect(watchMutate).toHaveBeenCalledTimes(1);

    // 180s of silence trips the watchdog; the scheduled recovery then
    // rebuilds the subscription and re-issues watch after its backoff.
    await vi.advanceTimersByTimeAsync(181_000);

    expect(subscriptions[0].unsubscribe).toHaveBeenCalled();
    expect(subscriptions).toHaveLength(2);
    expect(watchMutate).toHaveBeenCalledTimes(2);
  });

  it("stays quiet while heartbeats arrive", async () => {
    const { service, subscriptions, watchMutate } = createHarness();
    watchTask(service);
    await vi.advanceTimersByTimeAsync(0);

    for (let i = 0; i < 10; i++) {
      await vi.advanceTimersByTimeAsync(25_000);
      subscriptions[0].handlers.onData(heartbeat());
    }

    expect(subscriptions).toHaveLength(1);
    expect(watchMutate).toHaveBeenCalledTimes(1);
  });

  it("ignores errored and terminal sessions", async () => {
    const { service, sessions, subscriptions, watchMutate } = createHarness();
    watchTask(service);
    await vi.advanceTimersByTimeAsync(0);

    sessions[RUN_ID].status = "error";
    await vi.advanceTimersByTimeAsync(300_000);
    expect(subscriptions).toHaveLength(1);

    sessions[RUN_ID].status = "connected";
    sessions[RUN_ID].cloudStatus = "completed";
    await vi.advanceTimersByTimeAsync(300_000);
    expect(subscriptions).toHaveLength(1);
    expect(watchMutate).toHaveBeenCalledTimes(1);
  });

  it("leaves a stream alone while its recovery is still running", async () => {
    const { service, subscriptions, watchMutate } = createHarness();
    watchTask(service);
    await vi.advanceTimersByTimeAsync(0);

    let resolveWatch = () => {};
    watchMutate.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          resolveWatch = () => resolve();
        }),
    );

    subscriptions[0].handlers.onError?.(new Error("stream died"));
    await vi.advanceTimersByTimeAsync(1_000);
    expect(subscriptions).toHaveLength(2);

    // The rebuilt stream is silent because its watch call hasn't landed yet.
    // Treating that as a stall would queue a pointless second rebuild.
    await vi.advanceTimersByTimeAsync(300_000);
    expect(subscriptions).toHaveLength(2);

    resolveWatch();
    await vi.advanceTimersByTimeAsync(5_000);
    expect(subscriptions).toHaveLength(2);
    expect(watchMutate).toHaveBeenCalledTimes(2);
  });

  it("stops checking once the last watcher is gone", async () => {
    const { service, subscriptions } = createHarness();
    watchTask(service);
    await vi.advanceTimersByTimeAsync(0);

    service.stopCloudTaskWatch(TASK_ID);
    await vi.advanceTimersByTimeAsync(600_000);

    expect(subscriptions).toHaveLength(1);
  });
});
