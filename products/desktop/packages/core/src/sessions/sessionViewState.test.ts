import type { AcpMessage, AgentSession, StoredLogEntry } from "@posthog/shared";
import type { Task, TaskRunStatus } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { convertStoredEntriesToEvents } from "./sessionEvents";
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

function storedRunEvents(
  taskRunId: string,
  events: AcpMessage[],
): AcpMessage[] {
  const entries: StoredLogEntry[] = events.map((event) => ({
    type: "notification",
    timestamp: new Date(event.ts).toISOString(),
    notification: event.message,
  }));
  return convertStoredEntriesToEvents(entries, undefined, {
    taskRunId,
    startEntryIndex: 0,
  });
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
    session.events = storedRunEvents(session.taskRunId, [
      {
        type: "acp_message",
        ts: 2,
        message: {
          jsonrpc: "2.0",
          method: "_posthog/progress",
          params: {},
        },
      },
    ]);

    expect(
      deriveSessionViewState(session, makeTask("in_progress"), null, true)
        .isInitializing,
    ).toBe(true);
  });

  it("opens the live cloud chat after the active run sends its prompt", () => {
    const session = makeSession("in_progress");
    session.events = storedRunEvents(session.taskRunId, [
      {
        type: "acp_message",
        ts: 2,
        message: {
          jsonrpc: "2.0",
          id: 1,
          method: "session/prompt",
          params: {},
        },
      },
    ]);

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
    const state = deriveSessionViewState(
      makeSession("completed", "old-run"),
      makeTask("in_progress", "new-run"),
      null,
      true,
    );

    expect(state.cloudStatus).toBe("in_progress");
    expect(state.isCloudRunNotTerminal).toBe(true);
  });

  it.each([
    { isHydratingTranscript: true, expected: true },
    { isHydratingTranscript: undefined, expected: false },
  ])(
    "shows an empty terminal thread as initializing only while its transcript hydrates (hydrating: $isHydratingTranscript)",
    ({ isHydratingTranscript, expected }) => {
      const session = makeSession("completed");
      session.isHydratingTranscript = isHydratingTranscript;

      const state = deriveSessionViewState(
        session,
        makeTask("completed"),
        null,
        true,
      );

      expect(state.isInitializing).toBe(expected);
    },
  );

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
