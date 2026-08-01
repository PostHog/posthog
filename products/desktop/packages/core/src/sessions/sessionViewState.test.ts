import type { AgentSession } from "@posthog/shared";
import type { Task, TaskRunStatus } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { deriveSessionViewState } from "./sessionViewState";

function makeTask(runStatus: TaskRunStatus, runId = "run-1"): Task {
  return {
    id: "task-1",
    task_number: 1,
    slug: "task-1",
    title: "Task",
    description: "",
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    origin_product: "user_created",
    latest_run: {
      id: runId,
      status: runStatus,
      environment: "cloud",
    } as Task["latest_run"],
  };
}

function makeSession(
  cloudStatus: TaskRunStatus,
  taskRunId = "run-1",
): AgentSession {
  return {
    taskId: "task-1",
    taskRunId,
    taskTitle: "Task",
    channel: `agent-event:${taskRunId}`,
    status: "connected",
    events: [],
    startedAt: 0,
    isCloud: true,
    cloudStatus,
    isPromptPending: false,
    isCompacting: false,
    promptStartedAt: null,
    pendingPermissions: new Map(),
    pausedDurationMs: 0,
    messageQueue: [],
    optimisticItems: [],
  };
}

describe("deriveSessionViewState", () => {
  it("uses terminal task status over stale same-run session status", () => {
    const state = deriveSessionViewState(
      makeSession("in_progress"),
      makeTask("completed"),
      null,
      true,
    );

    expect(state.cloudStatus).toBe("completed");
    expect(state.isCloudRunTerminal).toBe(true);
    expect(state.isInitializing).toBe(false);
  });

  it("uses the task status when the session belongs to an older run", () => {
    const state = deriveSessionViewState(
      makeSession("completed", "old-run"),
      makeTask("in_progress", "new-run"),
      null,
      true,
    );

    expect(state.cloudStatus).toBe("in_progress");
    expect(state.isCloudRunNotTerminal).toBe(true);
  });

  it("treats not_started as a non-terminal cloud state", () => {
    const state = deriveSessionViewState(
      undefined,
      makeTask("not_started"),
      null,
      true,
    );

    expect(state.cloudStatus).toBe("not_started");
    expect(state.isCloudRunNotTerminal).toBe(true);
    expect(state.isCloudRunTerminal).toBe(false);
    expect(state.isInitializing).toBe(true);
  });
});
