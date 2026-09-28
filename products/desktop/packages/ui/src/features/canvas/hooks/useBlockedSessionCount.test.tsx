import type { AgentSession, PermissionRequest } from "@posthog/shared";
import {
  sessionStoreSetters,
  useSessionStore,
} from "@posthog/ui/features/sessions/sessionStore";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useBlockedTaskIds, useWorkingTaskIds } from "./useBlockedSessionCount";

function session(overrides: Partial<AgentSession> = {}): AgentSession {
  return {
    taskRunId: "run-1",
    taskId: "task-1",
    taskTitle: "Say hello",
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
    ...overrides,
  };
}

describe("session attention projections", () => {
  beforeEach(() => {
    useSessionStore.setState((state) => {
      state.sessions = {};
      state.taskIdIndex = {};
    });
  });

  // The reply flow behind a stale "Agent is waiting for your reply" row: the
  // agent asks, the user answers, and the agent takes the answer and works.
  it("hands the task from blocked to working when the user answers", () => {
    sessionStoreSetters.setSession(
      session({
        pendingPermissions: new Map([["tool-1", {} as PermissionRequest]]),
      }),
    );
    const blocked = renderHook(() => useBlockedTaskIds());
    const working = renderHook(() => useWorkingTaskIds());

    expect(blocked.result.current.has("task-1")).toBe(true);
    expect(working.result.current.has("task-1")).toBe(false);

    act(() => {
      sessionStoreSetters.setSession(session({ isPromptPending: true }));
    });

    expect(blocked.result.current.has("task-1")).toBe(false);
    expect(working.result.current.has("task-1")).toBe(true);
  });

  it("leaves an idle session out of both sets", () => {
    sessionStoreSetters.setSession(session());
    const blocked = renderHook(() => useBlockedTaskIds());
    const working = renderHook(() => useWorkingTaskIds());

    expect(blocked.result.current.has("task-1")).toBe(false);
    expect(working.result.current.has("task-1")).toBe(false);
  });
});
