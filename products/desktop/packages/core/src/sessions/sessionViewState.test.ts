import type { AgentSession } from "@posthog/shared";
import type { Task, TaskRunStatus } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  deriveSessionLifecycleState,
  deriveSessionViewState,
} from "./sessionViewState";

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
  it("opens the live cloud chat while setup events stream in", () => {
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
    ).toBe(false);
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

  it.each(["queued", "in_progress", "completed"] as const)(
    "keeps an unopened local %s run idle while its chat waits to reconnect",
    (status) => {
      const task = makeTask(status);
      if (task.latest_run) {
        task.latest_run.environment = "local";
      }

      expect(
        deriveSessionLifecycleState(undefined, task, false).isInitializing,
      ).toBe(false);
      expect(
        deriveSessionLifecycleState(undefined, task, false, true)
          .isInitializing,
      ).toBe(true);
      expect(
        deriveSessionViewState(undefined, task, null, false).isInitializing,
      ).toBe(true);
    },
  );

  it("opens a connecting local session, but not an older run's", () => {
    const task = makeTask("in_progress");
    if (task.latest_run) {
      task.latest_run.environment = "local";
    }
    const session = makeSession("in_progress");
    session.isCloud = false;
    session.status = "connecting";

    expect(
      deriveSessionViewState(session, task, null, false).isInitializing,
    ).toBe(false);

    const olderSession = makeSession("in_progress", "old-run");
    olderSession.isCloud = false;
    olderSession.status = "connecting";
    expect(
      deriveSessionViewState(olderSession, task, null, false).isInitializing,
    ).toBe(true);
  });

  it("opens a connected local task when no initial prompt remains to send", () => {
    const task = makeTask("in_progress");
    task.description = "Inspect the example task";
    if (task.latest_run) task.latest_run.environment = "local";
    const session = makeSession("in_progress");
    session.isCloud = false;

    const state = deriveSessionViewState(session, task, null, false);

    expect(state.isInitializing).toBe(false);
    expect(state.isRunning).toBe(true);
    expect(state.hasError).toBe(false);
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

  const oneEvent = [{} as AgentSession["events"][number]];

  it.each([
    {
      name: "local connecting shows the composer, not a full-panel spinner",
      isCloud: false,
      status: "connecting" as const,
      events: [] as AgentSession["events"],
      runStatus: "in_progress" as TaskRunStatus,
      isConnecting: true,
      isInitializing: false,
      isRunning: false,
    },
    {
      name: "local connecting with a painted tail is not initializing",
      isCloud: false,
      status: "connecting" as const,
      events: oneEvent,
      runStatus: "in_progress" as TaskRunStatus,
      isConnecting: true,
      isInitializing: false,
      isRunning: false,
    },
    {
      name: "local connected is neither connecting nor initializing",
      isCloud: false,
      status: "connected" as const,
      events: oneEvent,
      runStatus: "in_progress" as TaskRunStatus,
      isConnecting: false,
      isInitializing: false,
      isRunning: true,
    },
    {
      name: "cloud provisioning shows the composer while the sandbox spins up",
      isCloud: true,
      status: "connecting" as const,
      events: [] as AgentSession["events"],
      runStatus: "in_progress" as TaskRunStatus,
      isConnecting: true,
      isInitializing: false,
      isRunning: true,
    },
    {
      name: "cloud connected is not connecting",
      isCloud: true,
      status: "connected" as const,
      events: oneEvent,
      runStatus: "in_progress" as TaskRunStatus,
      isConnecting: false,
      isInitializing: false,
      isRunning: true,
    },
    {
      name: "a terminal cloud run is done, not connecting",
      isCloud: true,
      status: "connecting" as const,
      events: oneEvent,
      runStatus: "completed" as TaskRunStatus,
      isConnecting: false,
      isInitializing: false,
      isRunning: true,
    },
  ])(
    "$name",
    ({
      isCloud,
      status,
      events,
      runStatus,
      isConnecting,
      isInitializing,
      isRunning,
    }) => {
      const session = makeSession(runStatus);
      session.isCloud = isCloud;
      session.status = status;
      session.events = events;

      const state = deriveSessionViewState(
        session,
        makeTask(runStatus),
        null,
        isCloud,
      );

      expect(state.isConnecting).toBe(isConnecting);
      expect(state.isInitializing).toBe(isInitializing);
      expect(state.isRunning).toBe(isRunning);
    },
  );

  it("is not connecting before a session exists", () => {
    const state = deriveSessionViewState(
      undefined,
      makeTask("not_started"),
      null,
      true,
    );

    expect(state.isConnecting).toBe(false);
    expect(state.isInitializing).toBe(true);
  });
});

describe("deriveSessionLifecycleState", () => {
  it("keeps a local session starting until its first prompt", () => {
    const task = makeTask("in_progress");
    if (task.latest_run) {
      task.latest_run.environment = "local";
    }
    const session = makeSession("in_progress");
    session.isCloud = false;
    session.status = "connecting";

    expect(
      deriveSessionLifecycleState(session, task, false).isInitializing,
    ).toBe(true);

    session.status = "connected";
    session.initialPrompt = [
      { type: "text", text: "Inspect the example task" },
    ];
    expect(
      deriveSessionLifecycleState(session, task, false).isInitializing,
    ).toBe(true);

    session.firstPromptForRunId = session.taskRunId;
    expect(
      deriveSessionLifecycleState(session, task, false).isInitializing,
    ).toBe(false);
  });
});
