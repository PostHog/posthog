import type { AcpMessage, AgentSession } from "@posthog/shared";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SessionService, type SessionServiceDeps } from "./sessionService";

const TASK_ID = "task-1";
const RUN_ID = "run-1";
const FLUSH_MS = 16;

/** A plain streamed agent-message chunk — the common per-token event that just
 * gets appended to the transcript. */
function chunk(text: string): AcpMessage {
  return {
    ts: 1,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        sessionId: RUN_ID,
        update: {
          sessionUpdate: "agent_message_chunk",
          content: { type: "text", text },
        },
      },
    },
  } as unknown as AcpMessage;
}

function chunkText(event: AcpMessage): string {
  const params = (event.message as { params?: unknown }).params as {
    update: { content: { text: string } };
  };
  return params.update.content.text;
}

function createHarness() {
  const sessions: Record<string, AgentSession> = {
    [RUN_ID]: {
      taskRunId: RUN_ID,
      taskId: TASK_ID,
      taskTitle: "Local Task",
      events: [],
      messageQueue: [],
      pendingPermissions: new Map(),
      status: "connected",
    } as unknown as AgentSession,
  };

  const appendEvents = vi.fn(
    (taskRunId: string, events: AcpMessage[], newLineCount?: number) => {
      const session = sessions[taskRunId];
      if (!session) return;
      session.events = [...session.events, ...events];
      if (newLineCount !== undefined) session.processedLineCount = newLineCount;
    },
  );

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
    appendEvents,
    replaceOptimisticWithEvent: vi.fn(),
    setPendingPermissions: vi.fn(),
    clearMessageQueue: vi.fn(),
    clearTailOptimisticItems: vi.fn(),
    appendOptimisticItem: vi.fn(),
  };

  let onEvent: ((payload: unknown) => void) | undefined;
  const noopLog = {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  };

  const notifyPromptComplete = vi.fn();
  const deps = {
    store,
    log: noopLog,
    notifyPromptComplete,
    notifyPermissionRequest: vi.fn(),
    enqueueSpeech: vi.fn(),
    taskViewedApi: { markActivity: vi.fn() },
    getPersistedConfigOptions: () => undefined,
    setPersistedConfigOptions: vi.fn(),
    trpc: {
      agent: {
        onSessionEvent: {
          subscribe: (
            _input: unknown,
            handlers: { onData: (payload: unknown) => void },
          ) => {
            onEvent = handlers.onData;
            return { unsubscribe: vi.fn() };
          },
        },
        onPermissionRequest: {
          subscribe: () => ({ unsubscribe: vi.fn() }),
        },
        onSessionIdleKilled: {
          subscribe: () => ({ unsubscribe: vi.fn() }),
        },
      },
    },
  } as unknown as SessionServiceDeps;

  const service = new SessionService(deps);
  // Register the streamed-event subscription (captures onData).
  (
    service as unknown as { subscribeToChannel(id: string): void }
  ).subscribeToChannel(RUN_ID);
  if (!onEvent)
    throw new Error("subscribeToChannel did not subscribe to events");

  return {
    service,
    appendEvents,
    notifyPromptComplete,
    updateSession: store.updateSession,
    emit: (event: AcpMessage) => onEvent?.(event),
    events: () => sessions[RUN_ID].events,
  };
}

function promptEcho(id: number, ts: number): AcpMessage {
  return {
    ts,
    message: {
      jsonrpc: "2.0",
      id,
      method: "session/prompt",
      params: { sessionId: RUN_ID, prompt: [] },
    },
  } as unknown as AcpMessage;
}

function promptResponse(id: number, ts: number): AcpMessage {
  return {
    ts,
    message: {
      jsonrpc: "2.0",
      id,
      result: { stopReason: "end_turn" },
    },
  } as unknown as AcpMessage;
}

describe("streamed event batching", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("defers a burst and applies it on one flush tick, in order", () => {
    const h = createHarness();

    h.emit(chunk("a"));
    h.emit(chunk("b"));
    h.emit(chunk("c"));

    // Nothing is applied synchronously — the burst is buffered.
    expect(h.appendEvents).not.toHaveBeenCalled();
    expect(h.events()).toHaveLength(0);

    // A single flush tick drains the whole burst, in arrival order.
    vi.advanceTimersByTime(FLUSH_MS);
    expect(h.events().map(chunkText)).toEqual(["a", "b", "c"]);
  });

  it("flushes buffered events synchronously on teardown", () => {
    const h = createHarness();

    h.emit(chunk("a"));
    h.emit(chunk("b"));
    expect(h.events()).toHaveLength(0);

    // reset() tears down subscriptions and must not drop buffered events.
    h.service.reset();
    expect(h.events().map(chunkText)).toEqual(["a", "b"]);

    // The flush timer was cleared, so advancing does not re-apply anything.
    vi.advanceTimersByTime(FLUSH_MS);
    expect(h.events()).toHaveLength(2);
  });

  it("keeps the turn duration when the prompt mutation clears state before the response flushes", () => {
    const h = createHarness();

    h.emit(promptEcho(1, 1_000));
    vi.advanceTimersByTime(FLUSH_MS);

    h.emit(promptResponse(1, 6_000));
    h.updateSession(RUN_ID, { isPromptPending: false, promptStartedAt: null });
    vi.advanceTimersByTime(FLUSH_MS);

    expect(h.notifyPromptComplete).toHaveBeenCalledWith(
      "Local Task",
      "end_turn",
      TASK_ID,
      5_000,
    );
  });
});
