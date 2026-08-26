import type { AcpMessage, AgentSession } from "@posthog/shared";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POSTHOG_NOTIFICATIONS } from "./acpNotifications";
import { SessionService, type SessionServiceDeps } from "./sessionService";

const TASK_ID = "task-1";
const RUN_ID = "run-1";
const SESSION_EVENT_FLUSH_MS = 16;

function compactionStatus(status: string): AcpMessage {
  return {
    ts: 1,
    message: {
      jsonrpc: "2.0",
      method: POSTHOG_NOTIFICATIONS.STATUS,
      params: { sessionId: RUN_ID, status },
    },
  } as unknown as AcpMessage;
}

function createHarness(sessionOverrides: Partial<AgentSession> = {}) {
  const sessions: Record<string, AgentSession> = {
    [RUN_ID]: {
      taskRunId: RUN_ID,
      taskId: TASK_ID,
      taskTitle: "Local Task",
      events: [],
      messageQueue: [],
      pendingPermissions: new Map(),
      status: "connected",
      startedAt: 0,
      currentPromptId: null,
      adapter: "claude",
      isCloud: false,
      isPromptPending: false,
      isCompacting: false,
      ...sessionOverrides,
    } as unknown as AgentSession,
  };

  const store = {
    getSessions: () => sessions,
    getSessionByTaskId: (taskId: string) =>
      Object.values(sessions).find((s) => s.taskId === taskId),
    setSession: (session: AgentSession) => {
      sessions[session.taskRunId] = session;
    },
    updateSession: (taskRunId: string, updates: Partial<AgentSession>) => {
      const session = sessions[taskRunId];
      if (session) sessions[taskRunId] = { ...session, ...updates };
    },
    enqueueMessage: (taskId: string, text: string) => {
      const session = Object.values(sessions).find((s) => s.taskId === taskId);
      if (!session) return;
      sessions[session.taskRunId] = {
        ...session,
        messageQueue: [...session.messageQueue, { id: text, text }],
      } as unknown as AgentSession;
    },
    appendEvents: vi.fn(),
    replaceOptimisticWithEvent: vi.fn(),
    setPendingPermissions: vi.fn(),
    clearMessageQueue: vi.fn(),
    clearTailOptimisticItems: vi.fn(),
    clearOptimisticItems: vi.fn(),
    appendOptimisticItem: vi.fn(),
  };

  const cancelPrompt = vi.fn(async () => true);
  const prompt = vi.fn(async () => ({ stopReason: "end_turn" }));
  const sendCommand = vi.fn(async () => ({ success: true, result: {} }));
  let onEvent: ((payload: unknown) => void) | undefined;
  let cloudEntryCount = 0;

  const deps = {
    store,
    log: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
    track: vi.fn(),
    getIsOnline: () => true,
    addDirectoryDialog: { open: false },
    notifyPromptComplete: vi.fn(),
    notifyPermissionRequest: vi.fn(),
    enqueueSpeech: vi.fn(),
    toast: { error: vi.fn(), success: vi.fn() },
    usageLimit: { show: vi.fn() },
    taskViewedApi: { markActivity: vi.fn() },
    h: {
      extractSkillButtonId: () => undefined,
      getCloudPromptTransport: (p: string) => ({
        messageText: p,
        promptText: p,
        filePaths: [],
        skillBundles: [],
      }),
    },
    getPersistedConfigOptions: () => undefined,
    setPersistedConfigOptions: vi.fn(),
    trpc: {
      agent: {
        prompt: { mutate: prompt },
        cancelPrompt: { mutate: cancelPrompt },
        onSessionEvent: {
          subscribe: (
            _input: unknown,
            handlers: { onData: (payload: unknown) => void },
          ) => {
            onEvent = handlers.onData;
            return { unsubscribe: vi.fn() };
          },
        },
        onPermissionRequest: { subscribe: () => ({ unsubscribe: vi.fn() }) },
        onSessionIdleKilled: { subscribe: () => ({ unsubscribe: vi.fn() }) },
      },
      cloudTask: { sendCommand: { mutate: sendCommand } },
    },
  } as unknown as SessionServiceDeps;

  const service = new SessionService(deps);
  (
    service as unknown as { subscribeToChannel(id: string): void }
  ).subscribeToChannel(RUN_ID);
  if (!onEvent) throw new Error("subscribeToChannel did not subscribe");

  return {
    service,
    prompt,
    sendCommand,
    // Session events land in a batch the service flushes on a short timer.
    emit: async (event: AcpMessage) => {
      onEvent?.(event);
      await vi.advanceTimersByTimeAsync(SESSION_EVENT_FLUSH_MS);
    },
    // Cloud runs never use the ACP subscription above — their events arrive as
    // log entries on the run's stream.
    emitCloudLog: (notification: Record<string, unknown>) => {
      cloudEntryCount += 1;
      (
        service as unknown as {
          handleCloudTaskUpdate(runId: string, update: unknown): void;
        }
      ).handleCloudTaskUpdate(RUN_ID, {
        kind: "logs",
        taskId: TASK_ID,
        runId: RUN_ID,
        newEntries: [{ type: "notification", notification }],
        totalEntryCount: cloudEntryCount,
      });
    },
    isCompacting: () => sessions[RUN_ID].isCompacting,
  };
}

describe("compaction busy state", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("clears the busy flag when the compaction fails", async () => {
    const h = createHarness();
    await h.emit(compactionStatus("compacting"));
    expect(h.isCompacting()).toBe(true);

    await h.emit(compactionStatus("compacting_failed"));

    expect(h.isCompacting()).toBe(false);
    await h.service.sendPrompt(TASK_ID, "carry on");
    expect(h.prompt).toHaveBeenCalledTimes(1);
  });

  // Interrupting the turn can leave the adapter's failure status unsent, so the
  // cancel itself has to clear the flag or the session queues forever.
  it("clears the busy flag when the user cancels mid-compaction", async () => {
    const h = createHarness();
    await h.emit(compactionStatus("compacting"));

    await h.service.cancelPrompt(TASK_ID);

    expect(h.isCompacting()).toBe(false);
    await h.service.sendPrompt(TASK_ID, "carry on");
    expect(h.prompt).toHaveBeenCalledTimes(1);
  });

  // Cloud runs carry the status as a log entry rather than a live ACP message.
  // Miss it and a follow-up typed mid-compaction ships as a steer, which the
  // SDK folds into the running turn and the compaction aborts.
  it("queues a cloud steer sent while the agent is compacting", async () => {
    const h = createHarness({
      isCloud: true,
      cloudStatus: "in_progress",
      isPromptPending: true,
      optimisticItems: [],
      processedLineCount: 0,
    } as Partial<AgentSession>);

    h.emitCloudLog({
      method: POSTHOG_NOTIFICATIONS.STATUS,
      params: { sessionId: RUN_ID, status: "compacting" },
    });
    expect(h.isCompacting()).toBe(true);

    const result = await h.service.sendPrompt(TASK_ID, "carry on", {
      steer: true,
    });

    expect(result).toEqual({ stopReason: "queued" });
    expect(h.sendCommand).not.toHaveBeenCalled();
  });
});
