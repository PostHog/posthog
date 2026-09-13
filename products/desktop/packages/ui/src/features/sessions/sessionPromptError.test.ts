import { SessionConnectingError } from "@posthog/core/sessions/sessionErrors";
import { toast } from "@posthog/ui/primitives/toast";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { showSessionPromptError } from "./sessionPromptError";

const sessionState = vi.hoisted(() => ({
  session: {
    taskId: "task-1",
    status: "connecting",
    startedAt: 0,
  },
}));

vi.mock("@posthog/ui/features/sessions/sessionStore", () => ({
  sessionStoreSetters: {
    getSessionByTaskId: () => sessionState.session,
  },
}));

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: vi.fn() },
}));

describe("showSessionPromptError", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionState.session = {
      taskId: "task-1",
      status: "connecting",
      startedAt: Date.now(),
    };
  });

  it("shows one connecting notice after the session has waited 20 seconds", async () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date("2026-09-13T00:00:00Z"));
      sessionState.session.startedAt = Date.now();

      showSessionPromptError("task-1", new SessionConnectingError());
      showSessionPromptError("task-1", new SessionConnectingError());

      expect(toast.error).not.toHaveBeenCalled();

      await vi.advanceTimersByTimeAsync(19_999);
      expect(toast.error).not.toHaveBeenCalled();

      await vi.advanceTimersByTimeAsync(1);
      expect(toast.error).toHaveBeenCalledOnce();
      expect(toast.error).toHaveBeenCalledWith("Session is still connecting.", {
        id: "session-connecting-task-1",
      });

      showSessionPromptError("task-1", new SessionConnectingError());
      expect(toast.error).toHaveBeenCalledOnce();
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows other send errors immediately", () => {
    showSessionPromptError(
      "task-1",
      new Error("Agent server is not reachable"),
    );

    expect(toast.error).toHaveBeenCalledWith("Agent server is not reachable");
  });
});
