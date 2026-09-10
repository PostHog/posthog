import type { AcpMessage, AgentSession } from "@posthog/shared";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SessionService, type SessionServiceDeps } from "./sessionService";

const TASK_ID = "task-1";
const RUN_ID = "run-1";
const QUIET_MS = 250;
const MAX_WAIT_MS = 1_500;

function agentTextChunk(text: string): AcpMessage {
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

function toolCallUpdate(): AcpMessage {
  return {
    ts: 1,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        sessionId: RUN_ID,
        update: {
          sessionUpdate: "tool_call",
          toolCallId: "t1",
          status: "in_progress",
          title: "Bash",
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
      startedAt: 0,
      currentPromptId: 1,
      // No native steering, so a mid-turn message can only land by interrupting.
      steering: "interrupt-resend",
      adapter: "codex",
      isCloud: false,
      isPromptPending: true,
      isCompacting: false,
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
    appendEvents: vi.fn(),
    replaceOptimisticWithEvent: vi.fn(),
    setPendingPermissions: vi.fn(),
    clearMessageQueue: vi.fn(),
    clearTailOptimisticItems: vi.fn(),
    clearOptimisticItems: vi.fn(),
    appendOptimisticItem: vi.fn(),
    enqueueMessage: vi.fn(),
  };

  const cancelPrompt = vi.fn(async () => true);
  const prompt = vi.fn(async () => ({ stopReason: "end_turn" }));
  let onEvent: ((payload: unknown) => void) | undefined;

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
    h: { extractSkillButtonId: () => undefined },
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
    },
  } as unknown as SessionServiceDeps;

  const service = new SessionService(deps);
  (
    service as unknown as { subscribeToChannel(id: string): void }
  ).subscribeToChannel(RUN_ID);
  if (!onEvent) throw new Error("subscribeToChannel did not subscribe");

  return {
    service,
    cancelPrompt,
    prompt,
    emit: (event: AcpMessage) => onEvent?.(event),
    endTurn: () =>
      store.updateSession(RUN_ID, {
        isPromptPending: false,
        currentPromptId: null,
      }),
    // The turn ends and a message queued earlier immediately starts the next
    // one, which is what the turn-end drain does via its zero-delay timer.
    endTurnAndStartQueued: () => {
      store.updateSession(RUN_ID, {
        isPromptPending: false,
        currentPromptId: null,
      });
      setTimeout(() => {
        store.updateSession(RUN_ID, { isPromptPending: true });
      }, 0);
    },
    isPromptPending: () => sessions[RUN_ID].isPromptPending,
    steer: () =>
      service.sendPrompt(TASK_ID, "actually, do it the other way", {
        steer: true,
      }),
  };
}

describe("steering an adapter without native steering", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("waits for streamed text to go quiet before interrupting", async () => {
    const h = createHarness();
    h.emit(agentTextChunk("Let me explain"));

    const sent = h.steer();

    await vi.advanceTimersByTimeAsync(QUIET_MS - 50);
    expect(h.cancelPrompt).not.toHaveBeenCalled();

    // More text arrives, so the quiet window restarts rather than elapsing.
    h.emit(agentTextChunk(" the approach"));
    await vi.advanceTimersByTimeAsync(QUIET_MS - 50);
    expect(h.cancelPrompt).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(QUIET_MS);
    await sent;
    expect(h.cancelPrompt).toHaveBeenCalledTimes(1);
    expect(h.prompt).toHaveBeenCalledTimes(1);
  });

  it("interrupts without waiting when no text is streaming", async () => {
    const h = createHarness();
    // A tool call is running: nothing is mid-sentence to cut off.
    h.emit(toolCallUpdate());

    await h.steer();

    expect(h.cancelPrompt).toHaveBeenCalledTimes(1);
    expect(h.prompt).toHaveBeenCalledTimes(1);
  });

  it("interrupts at the ceiling when text never stops", async () => {
    const h = createHarness();
    h.emit(agentTextChunk("..."));
    const streaming = setInterval(() => h.emit(agentTextChunk("...")), 50);

    const sent = h.steer();
    await vi.advanceTimersByTimeAsync(MAX_WAIT_MS - 100);
    expect(h.cancelPrompt).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(200);
    clearInterval(streaming);
    await sent;
    expect(h.cancelPrompt).toHaveBeenCalledTimes(1);
  });

  // The steered turn ending hands the session to a message queued earlier.
  // Both flips land inside one sleep, so the wait never sees the idle gap and
  // only the turn's identity distinguishes the new turn from the steered one.
  it("does not interrupt a queued turn that starts while waiting", async () => {
    const h = createHarness();
    h.emit(agentTextChunk("wrapping up"));

    const sent = h.steer();
    h.endTurnAndStartQueued();

    await vi.advanceTimersByTimeAsync(QUIET_MS * 2);
    await sent;
    expect(h.isPromptPending()).toBe(true);
    expect(h.cancelPrompt).not.toHaveBeenCalled();
  });

  it("skips the interrupt when the turn ends while waiting", async () => {
    const h = createHarness();
    h.emit(agentTextChunk("wrapping up"));

    const sent = h.steer();
    h.endTurn();

    await vi.advanceTimersByTimeAsync(QUIET_MS * 2);
    await sent;
    expect(h.cancelPrompt).not.toHaveBeenCalled();
    expect(h.prompt).toHaveBeenCalledTimes(1);
  });
});
