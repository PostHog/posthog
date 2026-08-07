import type { AgentSession, ExecutionMode } from "@posthog/shared";
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
    isCloud: false,
    adapter: "claude",
    model: "claude-sonnet",
    executionMode: "plan",
    conversationClear: true,
    ...overrides,
  } as AgentSession;
}

function makePermission() {
  return {
    taskRunId: "run-1",
    receivedAt: 0,
    toolCallId: "tool-1",
    toolCall: {
      kind: "switch_mode",
      rawInput: { plan: "## Plan\n- fix bug" },
    },
    options: [
      { optionId: "auto", kind: "allow_always", name: "Auto" },
      {
        optionId: "clearAndContinue",
        kind: "allow_once",
        name: "Yes, clear history and continue from plan",
      },
    ],
  };
}

function createHarness(
  session: AgentSession,
  { stubContinuation = true }: { stubContinuation?: boolean } = {},
) {
  const sessions: Record<string, AgentSession> = {
    [session.taskRunId]: session,
  };
  const deps = {
    store: {
      getSessionByTaskId: (taskId: string) =>
        Object.values(sessions).find((s) => s.taskId === taskId),
      getSessions: () => sessions,
      removeSession: vi.fn((taskRunId: string) => {
        delete sessions[taskRunId];
      }),
      setSession: vi.fn((next: AgentSession) => {
        sessions[next.taskRunId] = next;
      }),
      updateSession: vi.fn(),
      setPendingPermissions: vi.fn(),
    },
    log: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
    trpc: {
      agent: {
        respondToPermission: { mutate: vi.fn().mockResolvedValue(undefined) },
        cancel: { mutate: vi.fn().mockResolvedValue(undefined) },
        cancelPrompt: { mutate: vi.fn().mockResolvedValue(undefined) },
        onSessionIdleKilled: {
          subscribe: () => ({ unsubscribe: vi.fn() }),
        },
      },
    },
    getIsOnline: () => true,
  } as unknown as SessionServiceDeps;

  const service = new SessionService(deps);
  const continueFromApprovedPlan = vi.spyOn(
    service,
    "continueFromApprovedPlan",
  );
  if (stubContinuation) continueFromApprovedPlan.mockResolvedValue(undefined);
  const respondToPermission = vi
    .spyOn(service, "respondToPermission")
    .mockResolvedValue(undefined);

  return { service, continueFromApprovedPlan, respondToPermission };
}

describe("SessionService plan continuation", () => {
  it.each<[string, Record<string, string> | undefined, ExecutionMode]>([
    ["the selected mode", { executionMode: "acceptEdits" }, "acceptEdits"],
    ["default when answers omit it", undefined, "default"],
    [
      "default when answers carry an unknown mode",
      { executionMode: "x" },
      "default",
    ],
  ])("continues from the plan with %s", async (_label, answers, expected) => {
    const { service, continueFromApprovedPlan, respondToPermission } =
      createHarness(makeSession());

    await service.resolvePermissionSelection(
      "task-1",
      makePermission() as never,
      "clearAndContinue",
      undefined,
      undefined,
      answers,
    );

    expect(continueFromApprovedPlan).toHaveBeenCalledWith(
      "task-1",
      "tool-1",
      "## Plan\n- fix bug",
      expected,
    );
    // Answering "allow" would let the agent start implementing in the stale
    // planning context before the clear lands.
    expect(respondToPermission).not.toHaveBeenCalled();
  });

  it("does not continue on normal approve", async () => {
    const { service, continueFromApprovedPlan, respondToPermission } =
      createHarness(makeSession());

    await service.resolvePermissionSelection(
      "task-1",
      makePermission() as never,
      "auto",
      undefined,
      undefined,
      undefined,
    );

    expect(continueFromApprovedPlan).not.toHaveBeenCalled();
    expect(respondToPermission).toHaveBeenCalledTimes(1);
  });

  it("approves without clearing when the agent cannot clear", async () => {
    const { service, continueFromApprovedPlan, respondToPermission } =
      createHarness(makeSession({ conversationClear: false }));

    await service.resolvePermissionSelection(
      "task-1",
      makePermission() as never,
      "clearAndContinue",
      undefined,
      undefined,
      { executionMode: "auto" },
    );

    // An agent predating the capability ignores the boundary and rebuilds the
    // conversation, so a clear here would be shown but not real.
    expect(continueFromApprovedPlan).not.toHaveBeenCalled();
    expect(respondToPermission).toHaveBeenCalledTimes(1);
  });

  it("does not continue on plan rejection", async () => {
    const { service, continueFromApprovedPlan } = createHarness(makeSession());

    await service.resolvePermissionSelection(
      "task-1",
      makePermission() as never,
      "reject_with_feedback",
      undefined,
      "try again",
      undefined,
    );

    expect(continueFromApprovedPlan).not.toHaveBeenCalled();
  });

  it("ends the planning turn and clears before sending the plan", async () => {
    const { service } = createHarness(makeSession(), {
      stubContinuation: false,
    });
    const cancelPermissionAndPrompt = vi
      .spyOn(service, "cancelPermissionAndPrompt")
      .mockResolvedValue(undefined);
    const setConfigOption = vi
      .spyOn(service, "setSessionConfigOptionByCategory")
      .mockResolvedValue(undefined);
    const sendPrompt = vi
      .spyOn(service, "sendPrompt")
      .mockResolvedValue({ stopReason: "end_turn" });

    await service.continueFromApprovedPlan(
      "task-1",
      "tool-1",
      "## Plan\n- fix bug",
      "acceptEdits",
    );

    expect(cancelPermissionAndPrompt).toHaveBeenCalledWith("task-1", "tool-1");
    expect(setConfigOption).toHaveBeenCalledWith(
      "task-1",
      "mode",
      "acceptEdits",
    );
    // Order is the whole feature: a plan sent before the clear lands in the
    // planning context the clear was meant to retire.
    expect(sendPrompt.mock.calls.map((call) => call[1])).toEqual([
      "/clear",
      [{ type: "text", text: expect.stringContaining("## Plan\n- fix bug") }],
    ]);
  });
});
