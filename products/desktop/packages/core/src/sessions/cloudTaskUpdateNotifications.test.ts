import type { AgentSession, StoredLogEntry } from "@posthog/shared";
import type { CloudTaskUpdatePayload } from "@posthog/shared/domain-types";
import { describe, expect, it, vi } from "vitest";
import { SessionService, type SessionServiceDeps } from "./sessionService";

const TASK_ID = "task-1";
const RUN_ID = "run-1";

function turnComplete(
  timestamp?: string,
  stopReason = "end_turn",
): StoredLogEntry {
  return {
    type: "notification",
    timestamp,
    notification: {
      method: "_posthog/turn_complete",
      params: { sessionId: RUN_ID, stopReason },
    },
  };
}

// The agent's JSON-RPC response to `session/prompt`. Real logs carry it next
// to `_posthog/turn_complete` in either order (the two writes race in the
// agent's log stream), so completion cases must ring for both orderings.
function promptResponse(
  id: number,
  stopReason = "end_turn",
  timestamp?: string,
): StoredLogEntry {
  return {
    type: "notification",
    timestamp,
    notification: { id, result: { stopReason } },
  };
}

// The `session/prompt` request that opens a turn. Its arrival is what arms the
// turn's single completion notification, so realistic sequences pair it with a
// later `turn_complete`.
function sessionPrompt(id: number, timestamp?: string): StoredLogEntry {
  return {
    type: "notification",
    timestamp,
    notification: {
      id,
      method: "session/prompt",
      params: { sessionId: RUN_ID, prompt: [] },
    },
  };
}

function permissionRequest(
  requestId: string,
  toolCallId: string,
): StoredLogEntry {
  return {
    type: "notification",
    notification: {
      method: "_posthog/permission_request",
      params: {
        requestId,
        toolCall: { toolCallId, title: "Run command", kind: "execute" },
        options: [],
      },
    },
  };
}

function logsUpdate(
  newEntries: StoredLogEntry[],
  totalEntryCount: number,
): CloudTaskUpdatePayload {
  return {
    taskId: TASK_ID,
    runId: RUN_ID,
    kind: "logs",
    newEntries,
    totalEntryCount,
  };
}

function snapshotUpdate(
  newEntries: StoredLogEntry[],
  totalEntryCount: number,
): CloudTaskUpdatePayload {
  return {
    taskId: TASK_ID,
    runId: RUN_ID,
    kind: "snapshot",
    newEntries,
    totalEntryCount,
  };
}

function createHarness() {
  const sessions: Record<string, AgentSession> = {};
  const store = {
    getSessions: () => sessions,
    getSessionByTaskId: (taskId: string) =>
      Object.values(sessions).find((s) => s.taskId === taskId),
    setSession: (session: AgentSession) => {
      sessions[session.taskRunId] = session;
    },
    updateSession: (taskRunId: string, updates: Partial<AgentSession>) => {
      const session = sessions[taskRunId];
      if (session) Object.assign(session, updates);
    },
    appendEvents: (
      taskRunId: string,
      events: AgentSession["events"],
      newLineCount?: number,
    ) => {
      const session = sessions[taskRunId];
      if (!session) return;
      session.events = [...session.events, ...events];
      if (newLineCount !== undefined) {
        session.processedLineCount = newLineCount;
      }
    },
    updateCloudStatus: (
      taskRunId: string,
      fields: { status?: AgentSession["cloudStatus"] },
    ) => {
      const session = sessions[taskRunId];
      if (session && fields.status !== undefined) {
        session.cloudStatus = fields.status;
      }
    },
    setPendingPermissions: (
      taskRunId: string,
      permissions: AgentSession["pendingPermissions"],
    ) => {
      const session = sessions[taskRunId];
      if (session) session.pendingPermissions = permissions;
    },
    clearTailOptimisticItems: vi.fn(),
    appendOptimisticItem: vi.fn(),
    replaceOptimisticWithEvent: vi.fn(),
    clearMessageQueue: vi.fn(),
  };

  let onUpdate: ((update: CloudTaskUpdatePayload) => void) | undefined;
  const notifyPromptComplete = vi.fn();
  const notifyPermissionRequest = vi.fn();
  const enqueueSpeech = vi.fn();
  const markActivity = vi.fn();
  const noopLog = {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  };

  const deps = {
    store,
    log: noopLog,
    notifyPromptComplete,
    notifyPermissionRequest,
    enqueueSpeech,
    taskViewedApi: { markActivity },
    getPersistedConfigOptions: () => undefined,
    setPersistedConfigOptions: vi.fn(),
    adapterStore: {
      getAdapter: () => undefined,
      setAdapter: vi.fn(),
      removeAdapter: vi.fn(),
    },
    trpc: {
      agent: {
        onSessionIdleKilled: {
          subscribe: () => ({ unsubscribe: vi.fn() }),
        },
        getPreviewConfigOptions: {
          query: vi.fn().mockResolvedValue([]),
        },
      },
      logs: {
        readLocalLogs: { query: vi.fn().mockResolvedValue("") },
      },
      cloudTask: {
        onUpdate: {
          subscribe: (
            _input: unknown,
            handlers: { onData: (update: CloudTaskUpdatePayload) => void },
          ) => {
            onUpdate = handlers.onData;
            return { unsubscribe: vi.fn() };
          },
        },
        watch: { mutate: vi.fn().mockResolvedValue(undefined) },
        unwatch: { mutate: vi.fn().mockResolvedValue(undefined) },
      },
    },
  } as unknown as SessionServiceDeps;

  const service = new SessionService(deps);
  service.watchCloudTask(TASK_ID, RUN_ID, "https://us.posthog.com", 1);
  if (!onUpdate) throw new Error("watchCloudTask did not subscribe");

  return {
    sendUpdate: (update: CloudTaskUpdatePayload) => onUpdate?.(update),
    notifyPromptComplete,
    notifyPermissionRequest,
    enqueueSpeech,
    markActivity,
  };
}

describe("cloud task update notifications", () => {
  it("does not notify for turn_completes replayed in a snapshot", () => {
    const harness = createHarness();

    harness.sendUpdate({
      taskId: TASK_ID,
      runId: RUN_ID,
      kind: "snapshot",
      newEntries: [turnComplete(), turnComplete(), turnComplete()],
      totalEntryCount: 3,
    });

    expect(harness.notifyPromptComplete).not.toHaveBeenCalled();
    expect(harness.markActivity).not.toHaveBeenCalled();
  });

  // Each case applies a sequence of updates to a fresh harness; `expected` is
  // the resulting notify count. Snapshots never ring; each armed turn rings at
  // most once even if the producer writes duplicate completion entries.
  it.each([
    {
      label: "a completion event without an armed turn",
      updates: [logsUpdate([turnComplete()], 1)],
      expected: 0,
    },
    {
      label: "a live turn that starts and completes",
      updates: [logsUpdate([sessionPrompt(1), turnComplete()], 2)],
      expected: 1,
    },
    {
      label: "several turns each completing",
      updates: [
        logsUpdate([sessionPrompt(1), turnComplete()], 2),
        logsUpdate([sessionPrompt(2), turnComplete()], 4),
      ],
      expected: 2,
    },
    {
      label: "duplicate completion events for one turn",
      updates: [
        logsUpdate([sessionPrompt(1), turnComplete()], 2),
        logsUpdate([turnComplete()], 3),
      ],
      expected: 1,
    },
    {
      label: "a turn whose response precedes turn_complete",
      updates: [
        logsUpdate([sessionPrompt(1), promptResponse(1), turnComplete()], 3),
      ],
      expected: 1,
    },
    {
      label: "a turn whose response follows turn_complete",
      updates: [
        logsUpdate([sessionPrompt(1), turnComplete(), promptResponse(1)], 3),
      ],
      expected: 1,
    },
    {
      label: "a duplicate turn_complete after a response-first turn",
      updates: [
        logsUpdate([sessionPrompt(1), promptResponse(1), turnComplete()], 3),
        logsUpdate([turnComplete()], 4),
      ],
      expected: 1,
    },
    {
      label: "several turns with responses on both sides of turn_complete",
      updates: [
        logsUpdate([sessionPrompt(1), promptResponse(1), turnComplete()], 3),
        logsUpdate([sessionPrompt(2), turnComplete(), promptResponse(2)], 6),
      ],
      expected: 2,
    },
    {
      label: "a cancelled turn",
      updates: [
        logsUpdate(
          [
            sessionPrompt(1),
            promptResponse(1, "cancelled"),
            turnComplete(undefined, "cancelled"),
          ],
          3,
        ),
      ],
      expected: 0,
    },
    {
      // Opening a task mid-turn: its session/prompt is already in history and
      // only the turn_complete arrives live. The completion must still ring.
      label: "a prompt seen only in the snapshot, completing live",
      updates: [
        snapshotUpdate([sessionPrompt(1)], 1),
        logsUpdate([turnComplete()], 2),
      ],
      expected: 1,
    },
  ])(
    "fires the completion notification once per turn: $label",
    ({ updates, expected }) => {
      const harness = createHarness();
      for (const update of updates) harness.sendUpdate(update);
      expect(harness.notifyPromptComplete).toHaveBeenCalledTimes(expected);
    },
  );

  it("notifies with the task title, stop reason and turn duration, and marks activity", () => {
    const harness = createHarness();
    harness.sendUpdate(
      logsUpdate(
        [
          sessionPrompt(1, "2026-01-01T00:00:00Z"),
          turnComplete("2026-01-01T00:00:45Z"),
        ],
        2,
      ),
    );

    expect(harness.notifyPromptComplete).toHaveBeenCalledWith(
      "Cloud Task",
      "end_turn",
      TASK_ID,
      45_000,
    );
    expect(harness.enqueueSpeech).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "done", source: "backstop" }),
    );
    expect(harness.markActivity).toHaveBeenCalledTimes(1);
  });

  it("keeps the turn duration when the response precedes turn_complete", () => {
    const harness = createHarness();
    harness.sendUpdate(
      logsUpdate(
        [
          sessionPrompt(1, "2026-01-01T00:00:00Z"),
          promptResponse(1, "end_turn", "2026-01-01T00:00:44Z"),
          turnComplete("2026-01-01T00:00:45Z"),
        ],
        3,
      ),
    );

    expect(harness.notifyPromptComplete).toHaveBeenCalledWith(
      "Cloud Task",
      "end_turn",
      TASK_ID,
      45_000,
    );
  });

  it("notifies a pending permission once across repeated snapshots", () => {
    const harness = createHarness();
    const snapshot = () =>
      harness.sendUpdate({
        taskId: TASK_ID,
        runId: RUN_ID,
        kind: "snapshot",
        newEntries: [permissionRequest("r1", "t1")],
        totalEntryCount: 1,
      });

    snapshot();
    expect(harness.notifyPermissionRequest).toHaveBeenCalledTimes(1);
    expect(harness.enqueueSpeech).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "needs_input", source: "backstop" }),
    );

    snapshot();
    snapshot();
    expect(harness.notifyPermissionRequest).toHaveBeenCalledTimes(1);
  });

  it("notifies again when the same tool call asks with a new requestId", () => {
    const harness = createHarness();
    harness.sendUpdate({
      taskId: TASK_ID,
      runId: RUN_ID,
      kind: "snapshot",
      newEntries: [permissionRequest("r1", "t1")],
      totalEntryCount: 1,
    });
    expect(harness.notifyPermissionRequest).toHaveBeenCalledTimes(1);

    harness.sendUpdate({
      taskId: TASK_ID,
      runId: RUN_ID,
      kind: "permission_request",
      requestId: "r2",
      toolCall: { toolCallId: "t1", title: "Run command", kind: "execute" },
      options: [],
    });
    expect(harness.notifyPermissionRequest).toHaveBeenCalledTimes(2);
  });
});
