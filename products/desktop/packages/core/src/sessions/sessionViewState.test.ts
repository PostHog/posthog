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
  it("keeps the loading view through optimistic prompts and setup events", () => {
    const session = makeSession("in_progress");
    session.optimisticItems = [
      {
        id: "initial-prompt",
        type: "user_message",
        content: "Check the build",
        timestamp: 1,
        pinToTop: true,
      },
    ];
    session.events = [
      {
        type: "acp_message",
        ts: 2,
        message: {
          jsonrpc: "2.0",
          method: "_posthog/progress",
          params: {},
        },
      },
    ];

    expect(
      deriveSessionViewState(session, makeTask("in_progress"), null, true)
        .isInitializing,
    ).toBe(true);
  });

  it("opens the live cloud chat after the active run sends its prompt", () => {
    const session = makeSession("in_progress");
    session.firstPromptForRunId = session.taskRunId;

    expect(
      deriveSessionViewState(session, makeTask("in_progress"), null, true)
        .isInitializing,
    ).toBe(false);
  });

  it("uses a live cloud session when task run metadata is unavailable", () => {
    const task = makeTask("in_progress");
    task.latest_run = undefined;

    const state = deriveSessionViewState(
      makeSession("in_progress"),
      task,
      null,
      false,
    );

    expect(state.isCloud).toBe(true);
    expect(state.isCloudRunNotTerminal).toBe(true);
  });

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
    const oldSession = makeSession("completed", "old-run");
    oldSession.status = "error";
    oldSession.firstPromptForRunId = "old-run";

    const state = deriveSessionViewState(
      oldSession,
      makeTask("in_progress", "new-run"),
      null,
      true,
      true,
    );

    expect(state.cloudStatus).toBe("in_progress");
    expect(state.isCloudRunNotTerminal).toBe(true);
    expect(state.hasError).toBe(false);
    expect(state.isInitializing).toBe(true);
  });

  it("uses a started session while task metadata still names the old run", () => {
    const session = makeSession("in_progress", "new-run");
    session.firstPromptForRunId = "new-run";
    session.resumeAncestorRunIds = ["older-run", "old-run"];

    const state = deriveSessionViewState(
      session,
      makeTask("failed", "old-run"),
      null,
      true,
    );

    expect(state.cloudStatus).toBe("in_progress");
    expect(state.isCloudRunTerminal).toBe(false);
    expect(state.isInitializing).toBe(false);
  });

  it("uses newer task metadata over an unrelated old session", () => {
    const session = makeSession("completed", "old-run");
    session.firstPromptForRunId = "old-run";

    const state = deriveSessionViewState(
      session,
      makeTask("in_progress", "new-run"),
      null,
      true,
    );

    expect(state.cloudStatus).toBe("in_progress");
    expect(state.isInitializing).toBe(true);
  });

  it("shows loading immediately when a new run starts from a terminal task", () => {
    const session = makeSession("failed");
    session.status = "error";

    const state = deriveSessionViewState(
      session,
      makeTask("failed"),
      null,
      true,
      true,
    );

    expect(state.isInitializing).toBe(true);
  });

  it("does not restore startup loading while a terminal transcript hydrates", () => {
    const session = makeSession("completed");
    session.isHydratingTranscript = true;

    const state = deriveSessionViewState(
      session,
      makeTask("completed"),
      null,
      true,
    );

    expect(state.isInitializing).toBe(false);
  });

  it("shows loading while a local session reconnects after reload", () => {
    const task = makeTask("in_progress");
    if (task.latest_run) {
      task.latest_run.environment = "local";
    }

    expect(
      deriveSessionViewState(undefined, task, null, false).isInitializing,
    ).toBe(true);
  });

  it("keeps a local session loading until its first prompt", () => {
    const task = makeTask("in_progress");
    if (task.latest_run) {
      task.latest_run.environment = "local";
    }
    const session = makeSession("in_progress");
    session.isCloud = false;
    session.status = "connecting";

    expect(
      deriveSessionViewState(session, task, null, false).isInitializing,
    ).toBe(true);

    session.status = "connected";
    session.firstPromptForRunId = session.taskRunId;
    expect(
      deriveSessionViewState(session, task, null, false).isInitializing,
    ).toBe(false);
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
