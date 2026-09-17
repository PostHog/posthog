import type { AgentSession, SessionStatus } from "@posthog/shared";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SessionService, type SessionServiceDeps } from "./sessionService";
import { sessionStore, sessionStoreSetters } from "./sessionStore";

const RUN = "run-res";
const TASK = "task-res";
const SECOND_RUN = "run-res-2";
const SECOND_TASK = "task-res-2";
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

function makeService(
  readLocalLogs = vi.fn().mockResolvedValue(""),
  getTaskRunSessionLogsPage = vi.fn(),
): SessionService {
  const deps = {
    store: sessionStoreSetters,
    log: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
    notifyPromptComplete: vi.fn(),
    notifyPermissionRequest: vi.fn(),
    taskViewedApi: { markActivity: vi.fn() },
    getPersistedConfigOptions: () => undefined,
    setPersistedConfigOptions: vi.fn(),
    fetchAuthState: vi.fn().mockResolvedValue({
      status: "authenticated",
      bootstrapComplete: true,
      cloudRegion: "us",
      currentProjectId: 1,
    }),
    createAuthenticatedClient: vi.fn().mockReturnValue({
      getTaskRunSessionLogsPage,
      getTaskRunSessionLogsResult: vi.fn(),
    }),
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

interface SeedOptions {
  taskRunId?: string;
  taskId?: string;
  status: SessionStatus;
  isPromptPending?: boolean;
  cloudStatus?: AgentSession["cloudStatus"];
  isHydratingTranscript?: boolean;
  withEvents?: boolean;
}

function seedSession({
  taskRunId = RUN,
  taskId = TASK,
  status,
  isPromptPending = false,
  cloudStatus,
  isHydratingTranscript,
  withEvents = true,
}: SeedOptions): void {
  sessionStoreSetters.setSession({
    taskRunId,
    taskId,
    events: [],
    messageQueue: [],
    pendingPermissions: new Map(),
    optimisticItems: [],
    status,
    isPromptPending,
    isCloud: cloudStatus !== undefined,
    cloudStatus,
    isHydratingTranscript,
  } as unknown as AgentSession);
  if (withEvents) {
    sessionStoreSetters.appendEvents(taskRunId, [
      { ts: 1, message: {} } as never,
    ]);
  }
}

function events(taskRunId = RUN): AgentSession["events"] {
  return sessionStore.getState().sessions[taskRunId]?.events ?? [];
}

function background(service: SessionService, taskId = TASK): void {
  service.scheduleEventEviction(taskId);
  vi.advanceTimersByTime(GRACE_MS);
}

function overflowBackgroundLru(service: SessionService): void {
  seedSession({
    taskRunId: SECOND_RUN,
    taskId: SECOND_TASK,
    status: "disconnected",
  });
  background(service, SECOND_TASK);
}

describe("session transcript residency", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
    sessionStoreSetters.clearAll();
  });

  it("keeps the previous disconnected transcript warm", () => {
    const service = makeService();
    seedSession({ status: "disconnected" });

    background(service);

    expect(events()).toHaveLength(1);
  });

  it("never backgrounds an active connected session", () => {
    const service = makeService();
    seedSession({ status: "connected" });

    background(service);

    expect(events()).toHaveLength(1);
  });

  it("never backgrounds an active cloud run reported disconnected mid-run", () => {
    const service = makeService();
    seedSession({ status: "disconnected", cloudStatus: "in_progress" });

    background(service);
    overflowBackgroundLru(service);

    expect(events(RUN)).toHaveLength(1);
  });

  it("keeps the previous completed cloud transcript warm", () => {
    const service = makeService();
    seedSession({ status: "connected", cloudStatus: "completed" });

    background(service);

    expect(events()).toHaveLength(1);
  });

  it("never backgrounds a session with a prompt in flight", () => {
    const service = makeService();
    seedSession({ status: "disconnected", isPromptPending: true });

    background(service);

    expect(events()).toHaveLength(1);
  });

  it("ensureEventsLoaded cancels pending backgrounding", async () => {
    const service = makeService();
    seedSession({ status: "disconnected" });
    service.scheduleEventEviction(TASK);

    await service.ensureEventsLoaded(TASK);
    vi.advanceTimersByTime(GRACE_MS);

    expect(events()).toHaveLength(1);
  });

  it("evicts the least recently viewed transcript when the LRU overflows", () => {
    const service = makeService();
    seedSession({ status: "disconnected" });
    background(service);

    overflowBackgroundLru(service);

    expect(events(RUN)).toHaveLength(0);
    expect(events(SECOND_RUN)).toHaveLength(1);
  });

  it.each([
    { label: "reconnected", revive: { status: "connected" as SessionStatus } },
    { label: "prompt in flight", revive: { isPromptPending: true } },
  ])(
    "does not evict a cached transcript that went live again ($label)",
    ({ revive }) => {
      const service = makeService();
      seedSession({ status: "disconnected" });
      background(service);

      sessionStoreSetters.updateSession(RUN, revive);

      overflowBackgroundLru(service);

      expect(events(RUN)).toHaveLength(1);
      expect(events(SECOND_RUN)).toHaveLength(1);
    },
  );

  it("keeps back-and-forth navigation warm", async () => {
    const readLocalLogs = vi.fn().mockResolvedValue(LOG_LINE);
    const service = makeService(readLocalLogs);
    seedSession({ status: "disconnected" });
    background(service);
    seedSession({
      taskRunId: SECOND_RUN,
      taskId: SECOND_TASK,
      status: "disconnected",
    });

    await service.ensureEventsLoaded(TASK);
    background(service, SECOND_TASK);
    await service.ensureEventsLoaded(SECOND_TASK);

    expect(events(RUN)).toHaveLength(1);
    expect(events(SECOND_RUN)).toHaveLength(1);
    expect(readLocalLogs).not.toHaveBeenCalled();
  });

  it("rehydrates an LRU-evicted transcript from disk on return", async () => {
    const readLocalLogs = vi.fn().mockResolvedValue(LOG_LINE);
    const service = makeService(readLocalLogs);
    seedSession({ status: "disconnected" });
    background(service);
    overflowBackgroundLru(service);

    await service.ensureEventsLoaded(TASK);

    expect(readLocalLogs).toHaveBeenCalledWith({ taskRunId: RUN });
    expect(events()).toHaveLength(1);
  });

  it("rehydrates a completed cloud transcript through its run chain", async () => {
    const getTaskRunSessionLogsPage = vi.fn().mockResolvedValue({
      entries: [JSON.parse(LOG_LINE)],
      hasMore: false,
      matchingCount: 1,
    });
    const readLocalLogs = vi.fn().mockResolvedValue("");
    const service = makeService(readLocalLogs, getTaskRunSessionLogsPage);
    seedSession({ status: "connected", cloudStatus: "completed" });
    background(service);
    overflowBackgroundLru(service);

    await service.ensureEventsLoaded(TASK);

    expect(getTaskRunSessionLogsPage).toHaveBeenCalledWith(TASK, RUN, {
      limit: 1,
    });
    expect(readLocalLogs).not.toHaveBeenCalled();
    expect(events()).toHaveLength(1);
  });

  it("enters the LRU after a terminal transcript hydrates past the grace window", () => {
    const service = makeService();
    seedSession({ status: "connected", cloudStatus: "completed" });
    background(service);

    seedSession({
      taskRunId: SECOND_RUN,
      taskId: SECOND_TASK,
      status: "connected",
      cloudStatus: "completed",
      isHydratingTranscript: true,
      withEvents: false,
    });
    background(service, SECOND_TASK);

    expect(events(RUN)).toHaveLength(1);
    expect(events(SECOND_RUN)).toHaveLength(0);

    sessionStoreSetters.updateSession(SECOND_RUN, {
      isHydratingTranscript: false,
    });
    sessionStoreSetters.appendEvents(SECOND_RUN, [
      { ts: 1, message: {} } as never,
    ]);

    vi.advanceTimersByTime(GRACE_MS);

    expect(events(SECOND_RUN)).toHaveLength(1);
    expect(events(RUN)).toHaveLength(0);
  });

  it("retries rehydration after a failed log read", async () => {
    const readLocalLogs = vi
      .fn()
      .mockRejectedValueOnce(new Error("transient"))
      .mockResolvedValueOnce(LOG_LINE);
    const service = makeService(readLocalLogs);
    seedSession({ status: "disconnected" });
    background(service);
    overflowBackgroundLru(service);

    await service.ensureEventsLoaded(TASK);
    expect(events()).toHaveLength(0);

    await service.ensureEventsLoaded(TASK);
    expect(events()).toHaveLength(1);
    expect(readLocalLogs).toHaveBeenCalledTimes(2);
  });
});
