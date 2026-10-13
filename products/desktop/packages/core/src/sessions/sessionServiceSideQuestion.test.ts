import type { AgentSession } from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import { SessionService, type SessionServiceDeps } from "./sessionService";

function makeSession(overrides: Partial<AgentSession> = {}): AgentSession {
  return {
    taskRunId: "run-1",
    taskId: "task-1",
    taskTitle: "Test task",
    channel: "",
    events: [],
    startedAt: 1,
    status: "connected",
    isPromptPending: false,
    isCompacting: false,
    promptStartedAt: null,
    pendingPermissions: new Map(),
    pausedDurationMs: 0,
    messageQueue: [],
    optimisticItems: [],
    adapter: "claude",
    ...overrides,
  } as AgentSession;
}

function createHarness(session: AgentSession | undefined, online = true) {
  const sideQuestionMutate = vi.fn().mockResolvedValue({ answer: "42" });
  const sendCommandMutate = vi
    .fn()
    .mockResolvedValue({ success: true, result: { answer: "42" } });
  const deps = {
    store: {
      getSessionByTaskId: () => session,
    },
    log: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
    getIsOnline: () => online,
    fetchAuthState: async () => ({
      cloudRegion: "us",
      currentProjectId: 7,
    }),
    trpc: {
      agent: {
        sideQuestion: { mutate: sideQuestionMutate },
        onSessionIdleKilled: {
          subscribe: () => ({ unsubscribe: vi.fn() }),
        },
      },
      cloudTask: {
        sendCommand: { mutate: sendCommandMutate },
      },
    },
  } as unknown as SessionServiceDeps;

  return {
    service: new SessionService(deps),
    sideQuestionMutate,
    sendCommandMutate,
  };
}

describe("SessionService.askSideQuestion", () => {
  it("sends the question keyed by taskRunId and returns the answer", async () => {
    const { service, sideQuestionMutate } = createHarness(makeSession());

    await expect(service.askSideQuestion("task-1", "why?")).resolves.toBe("42");
    expect(sideQuestionMutate).toHaveBeenCalledWith({
      sessionId: "run-1",
      question: "why?",
    });
  });

  it("rejects while offline", async () => {
    const { service, sideQuestionMutate } = createHarness(makeSession(), false);

    await expect(service.askSideQuestion("task-1", "why?")).rejects.toThrow(
      /No internet connection/,
    );
    expect(sideQuestionMutate).not.toHaveBeenCalled();
  });

  it("rejects when no session exists for the task", async () => {
    const { service } = createHarness(undefined);

    await expect(service.askSideQuestion("task-1", "why?")).rejects.toThrow(
      /No active session/,
    );
  });

  it("rejects a codex session as unsupported", async () => {
    const { service, sideQuestionMutate } = createHarness(
      makeSession({ adapter: "codex" }),
    );

    await expect(service.askSideQuestion("task-1", "why?")).rejects.toThrow(
      /aren't supported/,
    );
    expect(sideQuestionMutate).not.toHaveBeenCalled();
  });

  // Cloud sessions aren't in workspace-server's session map, so routing them
  // down the local path would fail at runtime.
  it("routes a cloud session over the command channel, not the local path", async () => {
    const { service, sideQuestionMutate, sendCommandMutate } = createHarness(
      makeSession({ isCloud: true }),
    );

    await expect(service.askSideQuestion("task-1", "why?")).resolves.toBe("42");
    expect(sideQuestionMutate).not.toHaveBeenCalled();
    expect(sendCommandMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        runId: "run-1",
        method: "side_question",
        params: { question: "why?" },
      }),
    );
  });

  it.each<[string, Record<string, unknown>]>([
    ["the command fails", { success: false, error: "sandbox is gone" }],
    ["the sandbox returns no answer", { success: true, result: {} }],
  ])("rejects a cloud side question when %s", async (_label, response) => {
    const { service, sendCommandMutate } = createHarness(
      makeSession({ isCloud: true }),
    );
    sendCommandMutate.mockResolvedValue(response);

    await expect(service.askSideQuestion("task-1", "why?")).rejects.toThrow();
  });

  it("rejects when the session is not connected", async () => {
    const { service, sideQuestionMutate } = createHarness(
      makeSession({ status: "connecting" }),
    );

    await expect(service.askSideQuestion("task-1", "why?")).rejects.toThrow(
      /not ready/,
    );
    expect(sideQuestionMutate).not.toHaveBeenCalled();
  });
});
