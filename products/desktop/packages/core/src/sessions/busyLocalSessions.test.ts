import type { AgentSession } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { countBusyLocalSessions } from "./busyLocalSessions";

function session(overrides: Partial<AgentSession>): AgentSession {
  return {
    taskRunId: "run-1",
    taskId: "task-1",
    taskTitle: "Task",
    channel: "channel",
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

describe("countBusyLocalSessions", () => {
  it.each([
    {
      name: "counts a local session with a prompt in flight",
      overrides: { isPromptPending: true },
      expected: 1,
    },
    {
      name: "ignores an idle local session",
      overrides: { isPromptPending: false },
      expected: 0,
    },
    {
      name: "ignores a cloud session even while it is working",
      overrides: { isCloud: true, isPromptPending: true },
      expected: 0,
    },
    {
      name: "ignores a disconnected local session with a stale pending prompt",
      overrides: { status: "disconnected" as const, isPromptPending: true },
      expected: 0,
    },
    {
      name: "ignores an errored local session",
      overrides: { status: "error" as const, isPromptPending: true },
      expected: 0,
    },
  ])("$name", ({ overrides, expected }) => {
    expect(countBusyLocalSessions({ "run-1": session(overrides) })).toBe(
      expected,
    );
  });

  it("counts across multiple sessions", () => {
    expect(
      countBusyLocalSessions({
        a: session({ taskRunId: "a", isPromptPending: true }),
        b: session({ taskRunId: "b", isPromptPending: true }),
        c: session({ taskRunId: "c", isCloud: true, isPromptPending: true }),
        d: session({ taskRunId: "d" }),
      }),
    ).toBe(2);
  });
});
