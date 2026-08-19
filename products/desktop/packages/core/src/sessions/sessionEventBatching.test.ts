import type { AcpMessage, AgentSession } from "@posthog/shared";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SessionService, type SessionServiceDeps } from "./sessionService";

const TASK_ID = "task-1";
const RUN_ID = "run-1";
const FLUSH_MS = 50;

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

function toolCall(id: string): AcpMessage {
  return {
    ts: 2,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        sessionId: RUN_ID,
        update: {
          sessionUpdate: "tool_call",
          toolCallId: id,
          title: "Read file",
          status: "in_progress",
        },
      },
    },
  } as unknown as AcpMessage;
}

function configOptionUpdate(): AcpMessage {
  return {
    ts: 3,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        sessionId: RUN_ID,
        update: {
          sessionUpdate: "config_option_update",
          configOptions: [
            {
              id: "mode",
              name: "Mode",
              category: "mode",
              type: "select",
              currentValue: "default",
              options: [],
            },
          ],
        },
      },
    },
  } as unknown as AcpMessage;
}

function usageUpdate(used: number, size: number): AcpMessage {
  return {
    ts: 4,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        sessionId: RUN_ID,
        update: { sessionUpdate: "usage_update", used, size },
      },
    },
  } as unknown as AcpMessage;
}

function completedSpeechToolCall(): AcpMessage {
  return {
    ts: 5,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        sessionId: RUN_ID,
        update: {
          sessionUpdate: "tool_call",
          toolCallId: "speak-1",
          status: "completed",
          _meta: {
            claudeCode: { toolName: "mcp__posthog-code-tools__speak" },
          },
          rawInput: { text: "Finished the task", kind: "done" },
        },
      },
    },
  } as unknown as AcpMessage;
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
  const enqueueSpeech = vi.fn();
  const setPersistedConfigOptions = vi.fn();
  const deps = {
    store,
    log: noopLog,
    notifyAgentSession: (notification: {
      kind: string;
      taskTitle: string;
      taskId: string;
      stopReason?: string;
      durationMs?: number;
    }) => {
      if (notification.kind === "turn_completed") {
        notifyPromptComplete(
          notification.taskTitle,
          notification.stopReason,
          notification.taskId,
          notification.durationMs,
        );
      }
    },
    enqueueSpeech,
    taskViewedApi: { markActivity: vi.fn() },
    getPersistedConfigOptions: () => undefined,
    setPersistedConfigOptions,
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
    enqueueSpeech,
    notifyPromptComplete,
    setPersistedConfigOptions,
    updateSession: store.updateSession,
    emit: (event: AcpMessage) => onEvent?.(event),
    events: () => sessions[RUN_ID].events,
    session: () => sessions[RUN_ID],
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
    expect(h.appendEvents).toHaveBeenCalledOnce();
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

  it("batches interleaved text and tool updates in order", () => {
    const h = createHarness();
    const streamed = chunk("a");
    const active = toolCall("tool-1");

    h.emit(streamed);
    h.emit(active);

    expect(h.events()).toEqual([]);
    vi.advanceTimersByTime(FLUSH_MS);
    expect(h.events()).toEqual([streamed, active]);
    expect(h.appendEvents).toHaveBeenCalledOnce();
  });

  it("applies context usage from a batched update", () => {
    const h = createHarness();

    h.emit(usageUpdate(25, 100));
    vi.advanceTimersByTime(FLUSH_MS);

    expect(h.session()).toMatchObject({ contextUsed: 25, contextSize: 100 });
  });

  it("enqueues completed speech from a batched tool update", () => {
    const h = createHarness();

    h.emit(completedSpeechToolCall());
    vi.advanceTimersByTime(FLUSH_MS);

    expect(h.enqueueSpeech).toHaveBeenCalledWith({
      text: "Finished the task",
      taskTitle: "Local Task",
      taskId: TASK_ID,
      kind: "done",
      source: "agent",
      addressByName: true,
    });
  });

  it("applies and persists config option updates immediately", () => {
    const h = createHarness();
    const streamed = chunk("a");
    const configUpdate = configOptionUpdate();

    h.emit(streamed);
    h.emit(configUpdate);

    expect(h.events()).toEqual([streamed, configUpdate]);
    expect(h.setPersistedConfigOptions).toHaveBeenCalledOnce();
  });

  it("contains errors from immediate session updates", () => {
    const h = createHarness();
    h.setPersistedConfigOptions.mockImplementation(() => {
      throw new Error("persist failed");
    });

    expect(() => h.emit(configOptionUpdate())).not.toThrow();
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
