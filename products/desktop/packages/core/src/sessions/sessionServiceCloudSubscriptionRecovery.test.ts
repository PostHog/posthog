import type { AgentSession } from "@posthog/shared";
import type { CloudTaskUpdatePayload } from "@posthog/shared/domain-types";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SessionService, type SessionServiceDeps } from "./sessionService";

const TASK_ID = "task-1";
const RUN_ID = "run-1";

type SubscriptionHandlers = {
  onData: (data: CloudTaskUpdatePayload) => void;
  onError?: (err: unknown) => void;
  onComplete?: () => void;
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
    // Model the worst-case transport, which completes the subscription
    // synchronously when it is unsubscribed — no test may recover in a loop.
    const unsubscribe = vi.fn(() => handlers.onComplete?.());
    subscriptions.push({ handlers, unsubscribe });
    return { unsubscribe };
  });
  const watchMutate = vi.fn().mockResolvedValue(undefined);
  const unwatchMutate = vi.fn().mockResolvedValue(undefined);

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
        unwatch: { mutate: unwatchMutate },
      },
    },
  } as unknown as SessionServiceDeps;

  const service = new SessionService(deps);
  return {
    service,
    sessions,
    store,
    subscriptions,
    watchMutate,
    unwatchMutate,
  };
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

async function flushMicrotasks() {
  await vi.advanceTimersByTimeAsync(0);
}

describe("SessionService cloud subscription recovery", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("rebuilds the subscription and re-issues watch after a subscription error", async () => {
    const { service, subscriptions, watchMutate } = createHarness();
    watchTask(service);
    await flushMicrotasks();
    expect(subscriptions).toHaveLength(1);
    expect(watchMutate).toHaveBeenCalledTimes(1);

    subscriptions[0].handlers.onError?.(new Error("stream died"));
    await vi.advanceTimersByTimeAsync(1_000);

    expect(subscriptions[0].unsubscribe).toHaveBeenCalled();
    expect(subscriptions).toHaveLength(2);
    expect(watchMutate).toHaveBeenCalledTimes(2);
    expect(watchMutate).toHaveBeenLastCalledWith({
      taskId: TASK_ID,
      runId: RUN_ID,
      apiHost: "https://us.posthog.com",
      teamId: 2,
      resumeFromEntryCount: undefined,
    });
  });

  it("recovers after the subscription completes without an error", async () => {
    const { service, subscriptions, watchMutate } = createHarness();
    watchTask(service);
    await flushMicrotasks();
    expect(subscriptions).toHaveLength(1);
    expect(watchMutate).toHaveBeenCalledTimes(1);

    // Host transport teardown ends the subscription cleanly (no error).
    subscriptions[0].handlers.onComplete?.();
    await vi.advanceTimersByTimeAsync(1_000);

    expect(subscriptions).toHaveLength(2);
    expect(watchMutate).toHaveBeenCalledTimes(2);

    // The recovery's own unsubscribe completes the old subscription; that
    // must not schedule another recovery against the rebuilt one.
    await vi.advanceTimersByTimeAsync(300_000);
    expect(subscriptions).toHaveLength(2);
    expect(watchMutate).toHaveBeenCalledTimes(2);
  });

  it("keeps retrying with backoff while the watch call fails", async () => {
    const { service, subscriptions, watchMutate } = createHarness();
    watchTask(service);
    await flushMicrotasks();
    watchMutate.mockRejectedValue(new Error("main process unavailable"));

    subscriptions[0].handlers.onError?.(new Error("stream died"));
    await vi.advanceTimersByTimeAsync(1_000);
    expect(subscriptions).toHaveLength(2);

    // Attempt counter is now 1, so the next retry waits 2s, not 1s.
    await vi.advanceTimersByTimeAsync(1_000);
    expect(subscriptions).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(subscriptions).toHaveLength(3);
  });

  it("surfaces a retryable error after repeated failed recoveries and clears it on success", async () => {
    const { service, sessions, subscriptions, watchMutate } = createHarness();
    watchTask(service);
    await flushMicrotasks();
    watchMutate.mockRejectedValue(new Error("main process unavailable"));

    subscriptions[0].handlers.onError?.(new Error("stream died"));
    // Attempts 1 (1s), 2 (2s), 3 (4s) — banner appears on the third failure.
    await vi.advanceTimersByTimeAsync(1_000 + 2_000);
    expect(sessions[RUN_ID].status).not.toBe("error");
    await vi.advanceTimersByTimeAsync(4_000);
    expect(sessions[RUN_ID].status).toBe("error");
    expect(sessions[RUN_ID].errorRetryable).toBe(true);

    watchMutate.mockResolvedValue(undefined);
    await vi.advanceTimersByTimeAsync(8_000);
    expect(sessions[RUN_ID].status).toBe("disconnected");
    expect(sessions[RUN_ID].errorTitle).toBeUndefined();
  });

  it("keeps a task error that lands while recovery is in flight", async () => {
    const { service, sessions, store, subscriptions, watchMutate } =
      createHarness();
    watchTask(service);
    await flushMicrotasks();
    watchMutate.mockRejectedValue(new Error("main process unavailable"));

    subscriptions[0].handlers.onError?.(new Error("stream died"));
    await vi.advanceTimersByTimeAsync(1_000 + 2_000 + 4_000);
    expect(sessions[RUN_ID].errorTitle).toBe("Stream connection lost");

    store.updateSession(RUN_ID, {
      status: "error",
      errorTitle: "Task failed",
      errorMessage: "The run crashed",
    });
    watchMutate.mockResolvedValue(undefined);
    await vi.advanceTimersByTimeAsync(8_000);

    expect(sessions[RUN_ID].status).toBe("error");
    expect(sessions[RUN_ID].errorTitle).toBe("Task failed");
  });

  it("unwatches the main process when teardown wins the recovery race", async () => {
    const { service, subscriptions, watchMutate, unwatchMutate } =
      createHarness();
    watchTask(service);
    await flushMicrotasks();

    let resolveWatch = () => {};
    watchMutate.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          resolveWatch = () => resolve();
        }),
    );

    subscriptions[0].handlers.onError?.(new Error("stream died"));
    await vi.advanceTimersByTimeAsync(1_000);
    expect(watchMutate).toHaveBeenCalledTimes(2);

    service.stopCloudTaskWatch(TASK_ID);
    resolveWatch();
    await flushMicrotasks();

    expect(unwatchMutate).toHaveBeenCalledWith({
      taskId: TASK_ID,
      runId: RUN_ID,
    });
  });

  it("stops recovering once the watch is torn down", async () => {
    const { service, subscriptions, watchMutate } = createHarness();
    watchTask(service);
    await flushMicrotasks();

    subscriptions[0].handlers.onError?.(new Error("stream died"));
    service.stopCloudTaskWatch(TASK_ID);
    await vi.advanceTimersByTimeAsync(60_000);

    expect(subscriptions).toHaveLength(1);
    expect(watchMutate).toHaveBeenCalledTimes(1);
  });

  it("resets the backoff once data flows again", async () => {
    const { service, subscriptions } = createHarness();
    watchTask(service);
    await flushMicrotasks();

    subscriptions[0].handlers.onError?.(new Error("stream died"));
    await vi.advanceTimersByTimeAsync(1_000);
    expect(subscriptions).toHaveLength(2);

    subscriptions[1].handlers.onData({
      taskId: TASK_ID,
      runId: RUN_ID,
      kind: "logs",
      newEntries: [],
      totalEntryCount: 1,
    });

    // A later error starts back at the initial delay instead of continuing
    // the previous backoff sequence.
    subscriptions[1].handlers.onError?.(new Error("stream died again"));
    await vi.advanceTimersByTimeAsync(1_000);
    expect(subscriptions).toHaveLength(3);
  });

  it("queues one retry instead of racing a second recovery", async () => {
    const { service, subscriptions, watchMutate } = createHarness();
    watchTask(service);
    await flushMicrotasks();

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
    expect(watchMutate).toHaveBeenCalledTimes(2);

    // The rebuilt subscription dies while its watch call is still in flight.
    // Recovering again now would leave the reference-counted main-process
    // watcher with two watch calls against one teardown.
    subscriptions[1].handlers.onError?.(new Error("stream died again"));
    await vi.advanceTimersByTimeAsync(30_000);
    expect(subscriptions).toHaveLength(2);
    expect(watchMutate).toHaveBeenCalledTimes(2);

    resolveWatch();
    await flushMicrotasks();
    await vi.advanceTimersByTimeAsync(2_000);
    expect(subscriptions).toHaveLength(3);
    expect(watchMutate).toHaveBeenCalledTimes(3);
  });

  it("ignores callbacks from a subscription recovery replaced", async () => {
    const { service, subscriptions, watchMutate } = createHarness();
    watchTask(service);
    await flushMicrotasks();

    subscriptions[0].handlers.onError?.(new Error("stream died"));
    await vi.advanceTimersByTimeAsync(1_000);
    expect(subscriptions).toHaveLength(2);

    subscriptions[0].handlers.onError?.(new Error("late error"));
    subscriptions[0].handlers.onComplete?.();
    await vi.advanceTimersByTimeAsync(30_000);

    expect(subscriptions).toHaveLength(2);
    expect(watchMutate).toHaveBeenCalledTimes(2);
  });
});
