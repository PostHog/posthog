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
    isCloud: false,
    adapter: "claude",
    model: "claude-sonnet",
    executionMode: "plan",
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

function createHarness(session: AgentSession) {
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
  const continueFromApprovedPlan = vi
    .spyOn(service, "continueFromApprovedPlan")
    .mockResolvedValue(undefined);
  const respondToPermission = vi
    .spyOn(service, "respondToPermission")
    .mockResolvedValue(undefined);

  return { service, continueFromApprovedPlan, respondToPermission };
}

describe("SessionService plan continuation", () => {
  it("continues only when clearAndContinue is selected", async () => {
    const session = makeSession();
    const { service, continueFromApprovedPlan, respondToPermission } =
      createHarness(session);

    await service.resolvePermissionSelection(
      "task-1",
      makePermission() as never,
      "clearAndContinue",
      undefined,
      undefined,
      { executionMode: "acceptEdits" },
      "/repo",
    );

    expect(continueFromApprovedPlan).toHaveBeenCalledWith(
      "task-1",
      "/repo",
      "## Plan\n- fix bug",
      "acceptEdits",
    );
    // The planning turn must NOT be answered "allow": doing so lets the old
    // session start generating in the stale context, and cancelling that
    // mid-stream is what closed the ACP connection for ~2s.
    expect(respondToPermission).not.toHaveBeenCalled();
  });

  it("does not continue on normal approve", async () => {
    const session = makeSession();
    const { service, continueFromApprovedPlan, respondToPermission } =
      createHarness(session);

    await service.resolvePermissionSelection(
      "task-1",
      makePermission() as never,
      "auto",
      undefined,
      undefined,
      undefined,
      "/repo",
    );

    expect(continueFromApprovedPlan).not.toHaveBeenCalled();
    // Normal approve still answers the permission in place.
    expect(respondToPermission).toHaveBeenCalledTimes(1);
  });

  it("does not continue without repoPath", async () => {
    const session = makeSession();
    const { service, continueFromApprovedPlan } = createHarness(session);

    await service.resolvePermissionSelection(
      "task-1",
      makePermission() as never,
      "clearAndContinue",
      undefined,
      undefined,
      { executionMode: "auto" },
    );

    expect(continueFromApprovedPlan).not.toHaveBeenCalled();
  });

  it("does not continue on plan rejection", async () => {
    const session = makeSession();
    const { service, continueFromApprovedPlan } = createHarness(session);

    await service.resolvePermissionSelection(
      "task-1",
      makePermission() as never,
      "reject_with_feedback",
      undefined,
      "try again",
      undefined,
      "/repo",
    );

    expect(continueFromApprovedPlan).not.toHaveBeenCalled();
  });

  it("defaults clear-and-continue mode to default when answers omit it", async () => {
    const session = makeSession();
    const { service, continueFromApprovedPlan } = createHarness(session);

    await service.resolvePermissionSelection(
      "task-1",
      makePermission() as never,
      "clearAndContinue",
      undefined,
      undefined,
      undefined,
      "/repo",
    );

    expect(continueFromApprovedPlan).toHaveBeenCalledWith(
      "task-1",
      "/repo",
      "## Plan\n- fix bug",
      "default",
    );
  });
});
