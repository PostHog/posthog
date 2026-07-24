import type { AgentSession, SessionStatus } from "@posthog/shared";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SessionService, type SessionServiceDeps } from "./sessionService";
import { sessionStore, sessionStoreSetters } from "./sessionStore";

const RUN = "run-res";
const TASK = "task-res";
const GRACE_MS = 20_000;

const LOG_LINE = JSON.stringify({
  type: "notification",
  notification: {
    method: "session/update",
    params: {
      sessionId: RUN,
      update: {
        sessionUpdate: "agent_message_chunk",
        content: { type: "text", text: "restored" },
      },
    },
  },
});

function makeService(readLocalLogs = vi.fn().mockResolvedValue("")) {
  const deps = {
    store: sessionStoreSetters,
    log: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
    notifyPromptComplete: vi.fn(),
    notifyPermissionRequest: vi.fn(),
    taskViewedApi: { markActivity: vi.fn() },
    getPersistedConfigOptions: () => undefined,
    setPersistedConfigOptions: vi.fn(),
    trpc: {
      agent: {
        onSessionEvent: { subscribe: () => ({ unsubscribe: vi.fn() }) },
        onPermissionRequest: { subscribe: () => ({ unsubscribe: vi.fn() }) },
        onSessionIdleKilled: { subscribe: () => ({ unsubscribe: vi.fn() }) },
      },
      logs: { readLocalLogs: { query: readLocalLogs } },
    },
  } as unknown as SessionServiceDeps;
  return new SessionService(deps);
}

function seed(status: SessionStatus, isPromptPending = false) {
  sessionStoreSetters.setSession({
    taskRunId: RUN,
    taskId: TASK,
    events: [],
    messageQueue: [],
    pendingPermissions: new Map(),
    status,
    isPromptPending,
  } as unknown as AgentSession);
  sessionStoreSetters.appendEvents(RUN, [{ ts: 1, message: {} } as never]);
}

const events = () => sessionStore.getState().sessions[RUN]?.events ?? [];

describe("session transcript residency", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    sessionStoreSetters.removeSession(RUN);
  });

  it("evicts a disconnected, idle session after the grace window", () => {
    const service = makeService();
    seed("disconnected");
    service.scheduleEventEviction(TASK);

    expect(events()).toHaveLength(1);
    vi.advanceTimersByTime(GRACE_MS);
    expect(events()).toHaveLength(0);
  });

  it("never evicts a connected session", () => {
    const service = makeService();
    seed("connected");
    service.scheduleEventEviction(TASK);

    vi.advanceTimersByTime(GRACE_MS);
    expect(events()).toHaveLength(1);
  });

  it("never evicts a session with a prompt in flight", () => {
    const service = makeService();
    seed("disconnected", true);
    service.scheduleEventEviction(TASK);

    vi.advanceTimersByTime(GRACE_MS);
    expect(events()).toHaveLength(1);
  });

  it("ensureEventsLoaded cancels a pending eviction", () => {
    const service = makeService();
    seed("disconnected");
    service.scheduleEventEviction(TASK);

    void service.ensureEventsLoaded(TASK); // return to the view before grace
    vi.advanceTimersByTime(GRACE_MS);
    expect(events()).toHaveLength(1);
  });

  it("rehydrates an evicted transcript from disk on return", async () => {
    const readLocalLogs = vi.fn().mockResolvedValue(LOG_LINE);
    const service = makeService(readLocalLogs);
    seed("disconnected");

    service.scheduleEventEviction(TASK);
    vi.advanceTimersByTime(GRACE_MS);
    expect(events()).toHaveLength(0);

    await service.ensureEventsLoaded(TASK);
    expect(readLocalLogs).toHaveBeenCalledWith({ taskRunId: RUN });
    expect(events()).toHaveLength(1);
  });

  it("retries rehydration after a failed log read instead of stranding it", async () => {
    const readLocalLogs = vi
      .fn()
      .mockRejectedValueOnce(new Error("transient"))
      .mockResolvedValueOnce(LOG_LINE);
    const service = makeService(readLocalLogs);
    seed("disconnected");

    service.scheduleEventEviction(TASK);
    vi.advanceTimersByTime(GRACE_MS);
    expect(events()).toHaveLength(0);

    // First visit: the log read throws — the transcript stays empty but the
    // run is re-marked evicted so a later visit can retry.
    await service.ensureEventsLoaded(TASK);
    expect(events()).toHaveLength(0);

    // Second visit: the read succeeds and the transcript is restored.
    await service.ensureEventsLoaded(TASK);
    expect(events()).toHaveLength(1);
    expect(readLocalLogs).toHaveBeenCalledTimes(2);
  });
});
