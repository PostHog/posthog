import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("expo-haptics", () => ({
  impactAsync: vi.fn(),
  notificationAsync: vi.fn(),
  ImpactFeedbackStyle: { Light: "light", Medium: "medium" },
  NotificationFeedbackType: { Success: "success" },
}));
vi.mock("../lib/cloudTaskStream", () => ({ watchCloudTask: vi.fn() }));
vi.mock("../composer/attachments/buildCloudPrompt", () => ({
  buildCloudPromptBlocks: vi.fn(() => Promise.resolve([])),
}));
vi.mock("../utils/sounds", () => ({
  playCompletionSound: vi.fn(() => Promise.resolve()),
}));
vi.mock("@/features/notifications/lib/notifications", () => ({
  presentLocalNotification: vi.fn(() => Promise.resolve()),
}));
vi.mock("../api", () => ({
  CloudCommandError: class CloudCommandError extends Error {},
  getTask: vi.fn(),
  runTaskInCloud: vi.fn(),
  sendCloudCommand: vi.fn(),
}));

import { usePreferencesStore } from "@/features/preferences/stores/preferencesStore";
import { getTask, runTaskInCloud } from "../api";
import type {
  CloudTaskUpdatePayload,
  StoredLogEntry,
  Task,
  TaskRun,
} from "../types";
import { useMessageQueueStore } from "./messageQueueStore";
import {
  mapTerminalStatus,
  type TaskSession,
  useTaskSessionStore,
} from "./taskSessionStore";
import { useTaskStore } from "./taskStore";

function seedSession(overrides: Partial<TaskSession> = {}): void {
  const session: TaskSession = {
    taskRunId: "run-1",
    taskId: "t1",
    events: [],
    status: "connected",
    isPromptPending: true,
    ...overrides,
  };
  useTaskSessionStore.setState({ sessions: { "run-1": session } });
}

describe("mapTerminalStatus", () => {
  it.each([
    { status: "completed", expected: "completed" },
    { status: "failed", expected: "failed" },
    { status: "cancelled", expected: "stopped" },
    { status: "in_progress", expected: undefined },
    { status: "queued", expected: undefined },
    { status: undefined, expected: undefined },
    { status: null, expected: undefined },
  ] as const)("maps $status to $expected", ({ status, expected }) => {
    expect(mapTerminalStatus(status)).toBe(expected);
  });
});

describe("steerQueuedMessage", () => {
  beforeEach(() => {
    useMessageQueueStore.setState({ queuesByTaskId: {} }, false);
    useTaskSessionStore.setState({ sessions: {} });
  });

  it("removes the message and resends it as a steer", async () => {
    seedSession();
    const sendInterrupting = vi.fn(() => Promise.resolve());
    useTaskSessionStore.setState({ sendInterrupting });

    useMessageQueueStore.getState().enqueue("t1", "first", []);
    useMessageQueueStore.getState().enqueue("t1", "second", []);
    const target = useMessageQueueStore.getState().getQueue("t1")[0];

    await useTaskSessionStore.getState().steerQueuedMessage("t1", target.id);

    expect(sendInterrupting).toHaveBeenCalledWith("t1", "first", []);
    expect(
      useMessageQueueStore
        .getState()
        .getQueue("t1")
        .map((m) => m.content),
    ).toEqual(["second"]);
  });

  it("rolls the message back onto the head when the resend fails", async () => {
    seedSession();
    const sendInterrupting = vi.fn(() => Promise.reject(new Error("boom")));
    useTaskSessionStore.setState({ sendInterrupting });

    useMessageQueueStore.getState().enqueue("t1", "first", []);
    useMessageQueueStore.getState().enqueue("t1", "second", []);
    const target = useMessageQueueStore.getState().getQueue("t1")[0];

    await expect(
      useTaskSessionStore.getState().steerQueuedMessage("t1", target.id),
    ).rejects.toThrow("boom");

    expect(
      useMessageQueueStore
        .getState()
        .getQueue("t1")
        .map((m) => m.content),
    ).toEqual(["first", "second"]);
  });

  it("no-ops while the session is compacting", async () => {
    seedSession({ isCompacting: true });
    const sendInterrupting = vi.fn(() => Promise.resolve());
    useTaskSessionStore.setState({ sendInterrupting });

    useMessageQueueStore.getState().enqueue("t1", "first", []);
    const target = useMessageQueueStore.getState().getQueue("t1")[0];

    await useTaskSessionStore.getState().steerQueuedMessage("t1", target.id);

    expect(sendInterrupting).not.toHaveBeenCalled();
    expect(
      useMessageQueueStore
        .getState()
        .getQueue("t1")
        .map((m) => m.content),
    ).toEqual(["first"]);
  });

  it("no-ops for an unknown message id", async () => {
    seedSession();
    const sendInterrupting = vi.fn(() => Promise.resolve());
    useTaskSessionStore.setState({ sendInterrupting });

    useMessageQueueStore.getState().enqueue("t1", "first", []);

    await useTaskSessionStore.getState().steerQueuedMessage("t1", "missing");

    expect(sendInterrupting).not.toHaveBeenCalled();
    expect(useMessageQueueStore.getState().getQueue("t1")).toHaveLength(1);
  });

  it("no-ops when no turn is running", async () => {
    seedSession({ isPromptPending: false });
    const sendInterrupting = vi.fn(() => Promise.resolve());
    useTaskSessionStore.setState({ sendInterrupting });

    useMessageQueueStore.getState().enqueue("t1", "first", []);
    const target = useMessageQueueStore.getState().getQueue("t1")[0];

    await useTaskSessionStore.getState().steerQueuedMessage("t1", target.id);

    expect(sendInterrupting).not.toHaveBeenCalled();
    expect(useMessageQueueStore.getState().getQueue("t1")).toHaveLength(1);
  });
});

describe("flushQueuedMessagesIfIdle", () => {
  beforeEach(() => {
    useMessageQueueStore.setState(
      { queuesByTaskId: {}, editingByTaskId: {} },
      false,
    );
    useTaskSessionStore.setState({ sessions: {} });
  });

  it("sends the queue when the agent is idle", async () => {
    seedSession({ isPromptPending: false });
    const sendInterrupting = vi.fn(() => Promise.resolve());
    useTaskSessionStore.setState({ sendInterrupting });
    useMessageQueueStore.getState().enqueue("t1", "a", []);
    useMessageQueueStore.getState().enqueue("t1", "b", []);

    useTaskSessionStore.getState().flushQueuedMessagesIfIdle("t1");
    await vi.waitFor(() => expect(sendInterrupting).toHaveBeenCalled());

    expect(sendInterrupting).toHaveBeenCalledWith("t1", "a\n\nb", []);
    expect(useMessageQueueStore.getState().getQueue("t1")).toEqual([]);
  });

  it("sends only the messages before the one being edited", async () => {
    seedSession({ isPromptPending: false });
    const sendInterrupting = vi.fn(() => Promise.resolve());
    useTaskSessionStore.setState({ sendInterrupting });
    useMessageQueueStore.getState().enqueue("t1", "a", []);
    useMessageQueueStore.getState().enqueue("t1", "b", []);
    useMessageQueueStore.getState().enqueue("t1", "c", []);
    const edited = useMessageQueueStore.getState().getQueue("t1")[1];
    useMessageQueueStore.getState().setEditing("t1", edited.id);

    useTaskSessionStore.getState().flushQueuedMessagesIfIdle("t1");
    await vi.waitFor(() => expect(sendInterrupting).toHaveBeenCalled());

    expect(sendInterrupting).toHaveBeenCalledWith("t1", "a", []);
    expect(
      useMessageQueueStore
        .getState()
        .getQueue("t1")
        .map((m) => m.content),
    ).toEqual(["b", "c"]);
  });

  it.each([
    { name: "a turn is running", overrides: { isPromptPending: true } },
    { name: "the run is terminal", overrides: { terminalStatus: "completed" } },
    { name: "the agent is compacting", overrides: { isCompacting: true } },
  ] as const)("no-ops when $name", async ({ overrides }) => {
    seedSession({ isPromptPending: false, ...overrides });
    const sendInterrupting = vi.fn(() => Promise.resolve());
    useTaskSessionStore.setState({ sendInterrupting });
    useMessageQueueStore.getState().enqueue("t1", "a", []);

    useTaskSessionStore.getState().flushQueuedMessagesIfIdle("t1");
    await Promise.resolve();

    expect(sendInterrupting).not.toHaveBeenCalled();
    expect(useMessageQueueStore.getState().getQueue("t1")).toHaveLength(1);
  });

  it("no-ops when the queue is empty", async () => {
    seedSession({ isPromptPending: false });
    const sendInterrupting = vi.fn(() => Promise.resolve());
    useTaskSessionStore.setState({ sendInterrupting });

    useTaskSessionStore.getState().flushQueuedMessagesIfIdle("t1");
    await Promise.resolve();

    expect(sendInterrupting).not.toHaveBeenCalled();
  });
});

describe("_resumeCloudRun", () => {
  const mockGetTask = vi.mocked(getTask);
  const mockRunTaskInCloud = vi.mocked(runTaskInCloud);

  function previousTask(latestRun: Partial<TaskRun>): Task {
    return {
      id: "t1",
      latest_run: { id: "prev-run", ...latestRun } as TaskRun,
    } as Task;
  }

  beforeEach(() => {
    vi.clearAllMocks();
    useTaskStore.setState({ composerConfigByTaskId: {} });
    useTaskSessionStore.setState({ sessions: {} });
    usePreferencesStore.setState({ rtkEnabledCloud: true });
    mockRunTaskInCloud.mockResolvedValue({
      id: "t1",
      latest_run: { id: "new-run" },
    } as Task);
  });

  it("forwards the previous run's effort and permission mode", async () => {
    mockGetTask.mockResolvedValue(
      previousTask({
        branch: "feature",
        reasoning_effort: "low",
        state: { initial_permission_mode: "acceptEdits" },
      }),
    );

    await useTaskSessionStore
      .getState()
      ._resumeCloudRun("t1", "prev-run", "hi");

    expect(mockRunTaskInCloud).toHaveBeenCalledWith("t1", {
      branch: "feature",
      resumeFromRunId: "prev-run",
      pendingUserMessage: "hi",
      reasoningEffort: "low",
      initialPermissionMode: "acceptEdits",
      rtkEnabled: true,
    });
  });

  it("forwards the rtk compression opt-out so resume preserves it", async () => {
    usePreferencesStore.setState({ rtkEnabledCloud: false });
    mockGetTask.mockResolvedValue(previousTask({ branch: "feature" }));

    await useTaskSessionStore
      .getState()
      ._resumeCloudRun("t1", "prev-run", "hi");

    expect(mockRunTaskInCloud).toHaveBeenCalledWith(
      "t1",
      expect.objectContaining({ rtkEnabled: false }),
    );
  });

  it("prefers the composer's current selection over the previous run", async () => {
    useTaskStore.setState({
      composerConfigByTaskId: { t1: { mode: "plan", reasoning: "max" } },
    });
    mockGetTask.mockResolvedValue(
      previousTask({
        branch: null,
        reasoning_effort: "low",
        state: { initial_permission_mode: "acceptEdits" },
      }),
    );

    await useTaskSessionStore
      .getState()
      ._resumeCloudRun("t1", "prev-run", "hi");

    expect(mockRunTaskInCloud).toHaveBeenCalledWith(
      "t1",
      expect.objectContaining({
        reasoningEffort: "max",
        initialPermissionMode: "plan",
      }),
    );
  });
});

describe("compaction tracking from the log stream", () => {
  beforeEach(() => {
    useTaskSessionStore.setState({ sessions: {} });
  });

  function statusEntry(isComplete: boolean): StoredLogEntry {
    return {
      type: "notification",
      notification: {
        method: "_posthog/status",
        params: { status: "compacting", isComplete },
      },
    };
  }

  function logsUpdate(entries: StoredLogEntry[]): CloudTaskUpdatePayload {
    return {
      kind: "logs",
      taskId: "t1",
      runId: "run-1",
      newEntries: entries,
      totalEntryCount: entries.length,
    };
  }

  it("sets isCompacting on a compacting status and clears it on the boundary", () => {
    seedSession({ isCompacting: false });
    const store = useTaskSessionStore.getState();

    store._handleCloudUpdate("run-1", logsUpdate([statusEntry(false)]));
    expect(store.getSessionForTask("t1")?.isCompacting).toBe(true);

    store._handleCloudUpdate(
      "run-1",
      logsUpdate([
        {
          type: "notification",
          notification: { method: "_posthog/compact_boundary" },
        },
      ]),
    );
    expect(store.getSessionForTask("t1")?.isCompacting).toBe(false);
  });
});
