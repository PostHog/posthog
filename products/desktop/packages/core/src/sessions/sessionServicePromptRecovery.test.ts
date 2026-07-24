import type { AgentSession } from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import { SessionService, type SessionServiceDeps } from "./sessionService";

const TASK_ID = "task-1";
const TASK_RUN_ID = `run-${TASK_ID}`;

function makeSession(): AgentSession {
  return {
    taskRunId: TASK_RUN_ID,
    taskId: TASK_ID,
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
  } as AgentSession;
}

function createHarness() {
  const sessions: Record<string, AgentSession> = {
    [TASK_RUN_ID]: makeSession(),
  };
  const store = {
    getSessions: () => sessions,
    getSessionByTaskId: (taskId: string) =>
      Object.values(sessions).find((s) => s.taskId === taskId),
    setSession: vi.fn((session: AgentSession) => {
      sessions[session.taskRunId] = session;
    }),
    updateSession: vi.fn((taskRunId: string, patch: Partial<AgentSession>) => {
      const existing = sessions[taskRunId];
      if (existing) sessions[taskRunId] = { ...existing, ...patch };
    }),
    appendOptimisticItem: vi.fn(),
    clearOptimisticItems: vi.fn(),
  };
  const promptMutate = vi.fn();
  const usageLimitShow = vi.fn();
  const deps = {
    store,
    h: { extractSkillButtonId: () => undefined },
    log: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
    toast: { error: vi.fn(), info: vi.fn() },
    track: vi.fn(),
    getIsOnline: () => true,
    addDirectoryDialog: { open: false },
    usageLimit: { show: usageLimitShow },
    trpc: {
      agent: {
        prompt: { mutate: promptMutate },
        cancel: { mutate: vi.fn().mockResolvedValue(undefined) },
        onSessionIdleKilled: {
          subscribe: () => ({ unsubscribe: vi.fn() }),
        },
      },
    },
  } as unknown as SessionServiceDeps;

  const service = new SessionService(deps);
  const recoverSpy = vi.spyOn(
    service as unknown as {
      tryAutoRecoverLocalSession: (
        taskId: string,
        taskRunId: string,
        reason: string,
      ) => Promise<boolean>;
    },
    "tryAutoRecoverLocalSession",
  );
  return { service, sessions, store, promptMutate, recoverSpy, usageLimitShow };
}

type RecoverSpy = ReturnType<typeof createHarness>["recoverSpy"];

describe("SessionService prompt recovery on fatal session errors", () => {
  it("recovers the session and resends the prompt once", async () => {
    const { service, promptMutate, recoverSpy } = createHarness();
    promptMutate
      .mockRejectedValueOnce(new Error(`Session not found: ${TASK_RUN_ID}`))
      .mockResolvedValueOnce({ stopReason: "end_turn" });
    recoverSpy.mockResolvedValue(true);

    const result = await service.sendPrompt(TASK_ID, "hello again");

    expect(result).toEqual({ stopReason: "end_turn" });
    expect(recoverSpy).toHaveBeenCalledTimes(1);
    expect(promptMutate).toHaveBeenCalledTimes(2);
  });

  it.each([
    {
      case: "recovery fails",
      setupRecovery: (spy: RecoverSpy) => spy.mockResolvedValue(false),
      expectedPromptCalls: 1,
    },
    {
      case: "the resend hits another fatal error",
      setupRecovery: (spy: RecoverSpy) => spy.mockResolvedValue(true),
      expectedPromptCalls: 2,
    },
    {
      case: "recovery throws",
      setupRecovery: (spy: RecoverSpy) =>
        spy.mockRejectedValue(new Error("auth restoring")),
      expectedPromptCalls: 1,
    },
  ])(
    "surfaces the error state and rethrows when $case",
    async ({ setupRecovery, expectedPromptCalls }) => {
      const { service, store, promptMutate, recoverSpy } = createHarness();
      promptMutate.mockRejectedValue(
        new Error(`Session not found: ${TASK_RUN_ID}`),
      );
      setupRecovery(recoverSpy);

      await expect(service.sendPrompt(TASK_ID, "hello again")).rejects.toThrow(
        "Session not found",
      );
      expect(recoverSpy).toHaveBeenCalledTimes(1);
      expect(promptMutate).toHaveBeenCalledTimes(expectedPromptCalls);
      expect(store.setSession).toHaveBeenCalledWith(
        expect.objectContaining({ taskRunId: TASK_RUN_ID, status: "error" }),
      );
    },
  );
});

describe("SessionService gateway billing denials", () => {
  it.each([
    {
      case: "a model-gate 403",
      message:
        'Internal error: API Error: 403 {"error":{"message":"Model \'claude-fable-5\' needs a paid PostHog plan. Models available on the free tier: @cf/zai-org/glm-5.2. Add a payment method to your organization to unlock all models. (rate_limit)","type":"permission_error","code":"model_gate"}}',
      expectedShow: { cause: "model_gate" },
    },
    {
      case: "an org-limit 429",
      message:
        "Rate limit exceeded: Your team has reached its PostHog Code usage limit for this billing period.",
      expectedShow: { cause: "org_limit" },
    },
    // The classified cause alone must open the modal — the org-limit prose
    // is not guaranteed to carry generic rate-limit wording.
    {
      case: "an org-limit message without rate-limit wording",
      message:
        "Your team has reached its PostHog Code usage limit for this billing period.",
      expectedShow: { cause: "org_limit" },
    },
    {
      case: "a free-tier valve 429",
      message: "Rate limit exceeded: User burst rate limit exceeded",
      expectedShow: { cause: "org_limit" },
    },
    {
      case: "an unclassified rate limit",
      message: "[429] Too many requests",
      expectedShow: undefined,
    },
  ])(
    "shows the usage-limit modal and stops the prompt for $case",
    async ({ message, expectedShow }) => {
      const { service, promptMutate, usageLimitShow, recoverSpy } =
        createHarness();
      promptMutate.mockRejectedValue(new Error(message));

      const result = await service.sendPrompt(TASK_ID, "hello");

      expect(result).toEqual({ stopReason: "rate_limited" });
      expect(usageLimitShow).toHaveBeenCalledWith(expectedShow);
      expect(recoverSpy).not.toHaveBeenCalled();
    },
  );
});
