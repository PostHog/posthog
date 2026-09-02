import { createUserMessageEvent } from "@posthog/core/sessions/sessionEvents";
import type { AgentSession } from "@posthog/shared";
import {
  sessionStoreSetters,
  useSessionStore,
} from "@posthog/ui/features/sessions/sessionStore";
import { useTurnStatusStore } from "@posthog/ui/features/sessions/turnStatusStore";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const generateTurnStatus = vi.hoisted(() => vi.fn());

vi.mock("@posthog/di/react", () => ({
  useService: () => ({ generateTurnStatus }),
}));

vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: (
    selector: (state: {
      status: string;
      cloudRegion: string | null;
    }) => unknown,
  ) => selector({ status: "authenticated", cloudRegion: "us-east-1" }),
}));

import { useTurnStatusGenerator } from "./useTurnStatusGenerator";

function createSession(events: AgentSession["events"]): AgentSession {
  return {
    taskRunId: "run-1",
    taskId: "task-1",
    taskTitle: "Improve search filters",
    channel: "main",
    events,
    startedAt: Date.now(),
    status: "connected",
    isPromptPending: true,
    isCompacting: false,
    promptStartedAt: Date.now(),
    pendingPermissions: new Map(),
    pausedDurationMs: 0,
    messageQueue: [],
    optimisticItems: [],
  };
}

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
} {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe("useTurnStatusGenerator", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSessionStore.setState({
      sessions: {},
      taskIdIndex: {},
      startingTaskIds: {},
    });
    useTurnStatusStore.setState({ byTaskId: {} });
  });

  it("keeps the latest turn status and clears it when the turn ends", async () => {
    const first = deferred<string | null>();
    const second = deferred<string | null>();
    generateTurnStatus
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    sessionStoreSetters.setSession(
      createSession([createUserMessageEvent("Improve search filters", 1)]),
    );
    renderHook(() => useTurnStatusGenerator("task-1"));

    await waitFor(() => expect(generateTurnStatus).toHaveBeenCalledTimes(1));

    act(() => {
      sessionStoreSetters.appendEvents("run-1", [
        createUserMessageEvent("Add saved filters", 2),
      ]);
    });
    await waitFor(() => expect(generateTurnStatus).toHaveBeenCalledTimes(2));

    await act(async () => {
      first.resolve("Improving search filters");
      await first.promise;
    });
    expect(useTurnStatusStore.getState().byTaskId["task-1"]?.text).toBeNull();

    await act(async () => {
      second.resolve("Adding saved filters");
      await second.promise;
    });
    await waitFor(() =>
      expect(useTurnStatusStore.getState().byTaskId["task-1"]?.text).toBe(
        "Adding saved filters",
      ),
    );

    act(() => {
      sessionStoreSetters.updateSession("run-1", { isPromptPending: false });
    });
    await waitFor(() =>
      expect(useTurnStatusStore.getState().byTaskId["task-1"]?.text).toBeNull(),
    );
  });
});
