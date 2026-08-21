import type { AgentSession } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/shell/rendererStorage", () => ({
  electronStorage: {
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  },
}));

const sessionService = vi.hoisted(() => ({
  updateQueuedMessage: vi.fn(),
  clearEditingQueuedMessage: vi.fn(),
  sendPrompt: vi.fn(),
  cancelPrompt: vi.fn(),
}));

vi.mock("@posthog/core/sessions/sessionService", () => ({
  SESSION_SERVICE: Symbol.for("test.session-service"),
}));

vi.mock("@posthog/ui/features/terminal/shellClient", () => ({
  SHELL_CLIENT: Symbol.for("test.shell-client"),
}));

vi.mock("@posthog/di/react", () => ({
  useService: (token: symbol) =>
    token === Symbol.for("test.session-service") ? sessionService : {},
}));

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPCClient: () => ({ skills: { list: { query: async () => [] } } }),
}));

const taskViewed = vi.hoisted(() => ({
  markActivity: vi.fn(),
  markAsViewed: vi.fn(),
}));
vi.mock("@posthog/ui/features/sidebar/useTaskViewed", () => ({
  useTaskViewed: () => taskViewed,
}));

const messagingMode = vi.hoisted(() => ({ value: "queue" }));
vi.mock("@posthog/ui/features/sessions/hooks/useMessagingMode", () => ({
  useMessagingMode: () => messagingMode.value,
}));

// No code command / skill rewrite by default; the raw text is used as the
// prompt. Kept as a spy so tests can inspect the CommandContext it received.
const tryExecuteCodeCommand = vi.hoisted(() =>
  vi.fn(async (_text: string, _ctx: Record<string, unknown>) => false),
);
vi.mock("@posthog/ui/features/message-editor/commands", () => ({
  tryExecuteCodeCommand,
  rewriteLocalSkillCommandPrompt: () => null,
  resolveLocalSkillPrompt: async (text: string) => text,
}));

const sessionState = vi.hoisted(() => ({
  editingQueuedId: "q-1" as string | undefined,
  messageQueue: [] as Array<{ id: string; content: string; queuedAt: number }>,
  isPromptPending: true,
  isCompacting: false,
  adapter: "claude" as const,
  isCloud: false,
  steering: "native",
}));
const dequeueMessages = vi.hoisted(() =>
  vi.fn(() => [] as Array<{ id: string; content: string; queuedAt: number }>),
);
vi.mock("@posthog/ui/features/sessions/sessionStore", () => ({
  sessionStoreSetters: {
    getSessionByTaskId: () => sessionState,
    dequeueMessages,
  },
}));

vi.mock("@posthog/ui/router/useAppView", () => ({
  getAppViewSnapshot: () => null,
}));

const { toastError, toastInfo } = vi.hoisted(() => ({
  toastError: vi.fn(),
  toastInfo: vi.fn(),
}));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: toastError, info: toastInfo },
}));

import { useDraftStore } from "@posthog/ui/features/message-editor/draftStore";
import { useSessionCallbacks } from "./useSessionCallbacks";

const TASK = "task-1";
const task = { id: TASK, latest_run: null } as unknown as Task;

function renderCallbacks(session?: AgentSession) {
  return renderHook(() =>
    useSessionCallbacks({
      taskId: TASK,
      task,
      session,
      repoPath: "/repo",
    }),
  );
}

function makeSession(overrides: Partial<AgentSession>): AgentSession {
  return {
    taskRunId: "run-1",
    taskId: TASK,
    taskTitle: "Test",
    channel: "agent-event:run-1",
    events: [],
    startedAt: 0,
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

describe("useSessionCallbacks.handleSendPrompt while editing a queued message", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionState.editingQueuedId = "q-1";
    sessionState.messageQueue = [];
    useDraftStore.setState((state) => ({
      ...state,
      drafts: {},
      pendingContent: {},
      _hasHydrated: true,
    }));
  });

  it("keeps the edit hold and does not send when the edit fails", async () => {
    sessionService.updateQueuedMessage.mockRejectedValue(
      new Error("cloud edit failed"),
    );

    const { result } = renderCallbacks();
    await result.current.handleSendPrompt("my edit");

    // The edit was attempted...
    expect(sessionService.updateQueuedMessage).toHaveBeenCalledWith(
      TASK,
      "q-1",
      "my edit",
    );
    // ...and it failed, so the user is told.
    expect(toastError).toHaveBeenCalled();
    // Critically: the hold is NOT released (which would drain and send the
    // original, unedited message) and no fresh prompt is sent.
    expect(sessionService.clearEditingQueuedMessage).not.toHaveBeenCalled();
    expect(sessionService.sendPrompt).not.toHaveBeenCalled();
    // The edited text is restored to the composer so the user can retry.
    expect(useDraftStore.getState().pendingContent[TASK]).toBeDefined();
  });

  it("releases the hold and sends fresh when the target is no longer queued", async () => {
    // updateQueuedMessage resolves false: the message already drained.
    sessionService.updateQueuedMessage.mockResolvedValue(false);
    sessionService.sendPrompt.mockResolvedValue(undefined);

    const { result } = renderCallbacks();
    await result.current.handleSendPrompt("my edit");

    // Stale hold dropped, and the edit is sent as a brand-new message.
    expect(sessionService.clearEditingQueuedMessage).toHaveBeenCalledWith(TASK);
    expect(sessionService.sendPrompt).toHaveBeenCalledWith(TASK, "my edit", {
      steer: false,
    });
  });

  it("updates in place and never sends when the edit saves", async () => {
    sessionService.updateQueuedMessage.mockResolvedValue(true);

    const { result } = renderCallbacks();
    await result.current.handleSendPrompt("my edit");

    expect(sessionService.updateQueuedMessage).toHaveBeenCalledWith(
      TASK,
      "q-1",
      "my edit",
    );
    expect(taskViewed.markAsViewed).toHaveBeenCalledWith(TASK);
    // Saving releases the hold inside the service, not the hook.
    expect(sessionService.clearEditingQueuedMessage).not.toHaveBeenCalled();
    expect(sessionService.sendPrompt).not.toHaveBeenCalled();
  });
});

describe("useSessionCallbacks.handleSendPrompt", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    messagingMode.value = "queue";
    sessionState.editingQueuedId = undefined;
    sessionState.messageQueue = [];
    sessionState.isPromptPending = true;
    sessionState.isCompacting = false;
  });

  it("reports a failed send so the composer keeps its content", async () => {
    sessionService.sendPrompt.mockRejectedValue(new Error("fetch failed"));

    const { result } = renderCallbacks();
    const sent = await result.current.handleSendPrompt("keep this message");

    expect(sent).toBe(false);
    expect(toastError).toHaveBeenCalledWith("fetch failed");
  });

  it("forwards the steer intent from the messaging mode", async () => {
    messagingMode.value = "steer";
    sessionService.sendPrompt.mockResolvedValue({ stopReason: "steered" });

    const { result } = renderCallbacks(sessionState as unknown as AgentSession);
    await result.current.handleSendPrompt("change direction");

    expect(sessionService.sendPrompt).toHaveBeenCalledWith(
      TASK,
      "change direction",
      { steer: true },
    );
  });
});

describe("useSessionCallbacks.handleCancelPrompt", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionState.editingQueuedId = undefined;
    sessionState.messageQueue = [];
    dequeueMessages.mockReturnValue([]);
    sessionService.cancelPrompt.mockResolvedValue(true);
    useDraftStore.setState((state) => ({
      ...state,
      drafts: {},
      pendingContent: {},
      _hasHydrated: true,
    }));
  });

  it("recalls the queue into the composer when no edit is active", async () => {
    dequeueMessages.mockReturnValue([
      { id: "q-1", content: "first", queuedAt: 1 },
      { id: "q-2", content: "second", queuedAt: 2 },
    ]);

    const { result } = renderCallbacks();
    await result.current.handleCancelPrompt();

    expect(sessionService.cancelPrompt).toHaveBeenCalledWith(TASK);
    expect(dequeueMessages).toHaveBeenCalledWith(TASK);
    expect(useDraftStore.getState().pendingContent[TASK]).toEqual({
      segments: [{ type: "text", text: "first\n\nsecond" }],
    });
  });

  it("stops without touching the queue or composer while an edit is active", async () => {
    sessionState.editingQueuedId = "q-1";
    sessionState.messageQueue = [{ id: "q-1", content: "old", queuedAt: 1 }];

    const { result } = renderCallbacks();
    await result.current.handleCancelPrompt();

    expect(sessionService.cancelPrompt).toHaveBeenCalledWith(TASK);
    // The queue is left in place (the edit hold keeps it from auto-sending)
    // and the composer keeps the in-progress edit.
    expect(dequeueMessages).not.toHaveBeenCalled();
    expect(useDraftStore.getState().pendingContent[TASK]).toBeUndefined();
  });

  it("falls back to the normal recall when the edit hold is stale", async () => {
    sessionState.editingQueuedId = "q-gone";
    sessionState.messageQueue = [{ id: "q-1", content: "first", queuedAt: 1 }];
    dequeueMessages.mockReturnValue([
      { id: "q-1", content: "first", queuedAt: 1 },
    ]);

    const { result } = renderCallbacks();
    await result.current.handleCancelPrompt();

    expect(dequeueMessages).toHaveBeenCalledWith(TASK);
    expect(useDraftStore.getState().pendingContent[TASK]).toEqual({
      segments: [{ type: "text", text: "first" }],
    });
  });
});

describe("useSessionCallbacks.handleSendPrompt askSideQuestion gating", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionState.editingQueuedId = undefined;
    sessionState.messageQueue = [];
  });

  it("passes a callable askSideQuestion for a session that supports it", async () => {
    const { result } = renderHook(() =>
      useSessionCallbacks({
        taskId: TASK,
        task,
        session: makeSession({ isCloud: false, sideQuestion: true }),
        repoPath: "/repo",
      }),
    );
    await result.current.handleSendPrompt("/btw what changed?");

    const ctx = tryExecuteCodeCommand.mock.calls.at(-1)?.[1];
    expect(ctx).toBeDefined();
    expect(ctx?.askSideQuestion).toBeInstanceOf(Function);
  });

  it("passes undefined askSideQuestion for a session that does not support it", async () => {
    const { result } = renderHook(() =>
      useSessionCallbacks({
        taskId: TASK,
        task,
        session: makeSession({ sideQuestion: false }),
        repoPath: "/repo",
      }),
    );
    await result.current.handleSendPrompt("/btw what changed?");

    const ctx = tryExecuteCodeCommand.mock.calls.at(-1)?.[1];
    expect(ctx).toBeDefined();
    expect(ctx?.askSideQuestion).toBeUndefined();
  });
});
