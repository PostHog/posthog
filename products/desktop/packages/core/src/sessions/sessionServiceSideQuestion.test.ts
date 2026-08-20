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
  const deps = {
    store: {
      getSessionByTaskId: () => session,
    },
    log: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
    getIsOnline: () => online,
    trpc: {
      agent: {
        sideQuestion: { mutate: sideQuestionMutate },
        onSessionIdleKilled: {
          subscribe: () => ({ unsubscribe: vi.fn() }),
        },
      },
    },
  } as unknown as SessionServiceDeps;

  return { service: new SessionService(deps), sideQuestionMutate };
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

  it.each<[string, Partial<AgentSession>]>([
    ["cloud session", { isCloud: true, sideQuestion: true }],
    ["codex without the capability", { adapter: "codex" }],
  ])("rejects a %s as unsupported", async (_label, overrides) => {
    const { service, sideQuestionMutate } = createHarness(
      makeSession(overrides),
    );

    await expect(service.askSideQuestion("task-1", "why?")).rejects.toThrow(
      /aren't supported/,
    );
    expect(sideQuestionMutate).not.toHaveBeenCalled();
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
