import type { TaskRunStatus } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  deriveTaskData,
  deriveTaskRunState,
  limitTasksPerGroup,
  narrowFullTask,
  type RunMode,
  readRunMode,
  sliceVisibleTasks,
  type TaskSession,
} from "./buildSidebarData";
import type { TaskData, TaskGroup } from "./sidebarData.types";

function makeTask(id: string): TaskData {
  return {
    id,
    title: `Task ${id}`,
    createdAt: 0,
    lastActivityAt: 0,
    isGenerating: false,
    isUnread: false,
    isPinned: false,
    needsPermission: false,
    repository: null,
    isSuspended: false,
    folderPath: null,
    cloudPrUrl: null,
    branchName: null,
    linkedBranch: null,
  };
}

function makeGroup(id: string, taskCount: number): TaskGroup {
  return {
    id,
    name: id,
    tasks: Array.from({ length: taskCount }, (_, i) => makeTask(`${id}-${i}`)),
  };
}

describe("deriveTaskRunState", () => {
  it.each<
    [
      string,
      TaskRunStatus,
      "local" | "cloud",
      RunMode | undefined,
      TaskSession | undefined,
      boolean,
    ]
  >([
    [
      "a background cloud run reconnects",
      "in_progress",
      "cloud",
      "background",
      undefined,
      true,
    ],
    [
      "an interactive cloud run waits after restart",
      "in_progress",
      "cloud",
      "interactive",
      undefined,
      false,
    ],
    [
      "an older server omits the cloud run mode",
      "in_progress",
      "cloud",
      undefined,
      undefined,
      false,
    ],
    [
      "a cloud run waits for setup",
      "not_started",
      "cloud",
      undefined,
      undefined,
      true,
    ],
    [
      "a matching cloud session has no activity evidence",
      "in_progress",
      "cloud",
      "interactive",
      { taskRunId: "run-1" },
      false,
    ],
    [
      "the current interactive cloud run has a prompt in flight",
      "in_progress",
      "cloud",
      "interactive",
      { taskRunId: "run-1", isPromptPending: true },
      true,
    ],
    [
      "the current cloud run reports idle",
      "in_progress",
      "cloud",
      "background",
      { taskRunId: "run-1", agentIdleForRunId: "run-1" },
      false,
    ],
    [
      "a session for another background run reports idle",
      "in_progress",
      "cloud",
      "background",
      { taskRunId: "run-2", agentIdleForRunId: "run-2" },
      true,
    ],
    [
      "a session for another run cannot activate an interactive run",
      "in_progress",
      "cloud",
      "interactive",
      { taskRunId: "run-2", agentIdleForRunId: "run-2" },
      false,
    ],
    [
      "the previous run left an idle marker",
      "in_progress",
      "cloud",
      "background",
      { taskRunId: "run-1", agentIdleForRunId: "run-0" },
      true,
    ],
    [
      "an old cloud session still reports work",
      "completed",
      "cloud",
      "background",
      { taskRunId: "run-0", cloudStatus: "in_progress" },
      false,
    ],
    [
      "the current cloud run settles while the session lags",
      "completed",
      "cloud",
      "background",
      {
        taskRunId: "run-1",
        cloudStatus: "in_progress",
        isPromptPending: true,
      },
      false,
    ],
    [
      "a cloud run completes",
      "completed",
      "cloud",
      "background",
      undefined,
      false,
    ],
    [
      "a local run stays in progress",
      "in_progress",
      "local",
      undefined,
      undefined,
      false,
    ],
    [
      "a local agent streams output",
      "in_progress",
      "local",
      undefined,
      { taskRunId: "run-1", isPromptPending: true },
      true,
    ],
    [
      "an old local session streams output",
      "in_progress",
      "local",
      undefined,
      { taskRunId: "run-0", isPromptPending: true },
      false,
    ],
  ])(
    "derives loading for %s",
    (_case, status, environment, mode, session, expected) => {
      const result = deriveTaskRunState(
        {
          id: "task-1",
          latest_run: { id: "run-1", status, environment, mode },
        },
        session,
      );

      expect(result.isGenerating).toBe(expected);
    },
  );

  it.each([
    ["the latest run", "run-1", true],
    ["an older run", "run-0", false],
  ])("reads pending permissions from %s", (_case, taskRunId, expected) => {
    const result = deriveTaskRunState(
      {
        id: "task-1",
        latest_run: {
          id: "run-1",
          status: "in_progress",
          environment: "cloud",
          mode: "interactive",
        },
      },
      { taskRunId, pendingPermissions: { size: 1 } },
    );

    expect(result.needsPermission).toBe(expected);
  });
});

describe("sliceVisibleTasks", () => {
  it("caps the flat list to the visible count and reports hasMore", () => {
    const tasks = Array.from({ length: 30 }, (_, i) => makeTask(String(i)));
    const { flatTasks, hasMore } = sliceVisibleTasks(tasks, 25);
    expect(flatTasks).toHaveLength(25);
    expect(flatTasks[0]?.id).toBe("0");
    expect(hasMore).toBe(true);
  });

  it("returns every task and hasMore=false when under the cap", () => {
    const tasks = Array.from({ length: 10 }, (_, i) => makeTask(String(i)));
    const { flatTasks, hasMore } = sliceVisibleTasks(tasks, 25);
    expect(flatTasks).toHaveLength(10);
    expect(hasMore).toBe(false);
  });

  it("reports hasMore=false when the count exactly matches the cap", () => {
    const tasks = Array.from({ length: 25 }, (_, i) => makeTask(String(i)));
    expect(sliceVisibleTasks(tasks, 25).hasMore).toBe(false);
  });
});

describe("limitTasksPerGroup", () => {
  it("caps each group independently so quiet groups still show tasks", () => {
    const groups = [makeGroup("busy", 40), makeGroup("quiet", 3)];
    const { groups: limited, hasMore } = limitTasksPerGroup(groups, 25);
    expect(limited[0]?.tasks).toHaveLength(25);
    expect(limited[1]?.tasks).toHaveLength(3);
    expect(hasMore).toBe(true);
  });

  it("keeps empty groups (e.g. registered folders with no tasks)", () => {
    const groups = [makeGroup("empty", 0)];
    const { groups: limited, hasMore } = limitTasksPerGroup(groups, 25);
    expect(limited[0]?.tasks).toHaveLength(0);
    expect(hasMore).toBe(false);
  });

  it("does not clone groups that are under the cap", () => {
    const groups = [makeGroup("small", 5)];
    const { groups: limited, hasMore } = limitTasksPerGroup(groups, 25);
    expect(limited[0]).toBe(groups[0]);
    expect(hasMore).toBe(false);
  });
});

// The mode decides whether a run's `in_progress` is a claim that work is
// happening. Defaulting the wrong way marks every finished interactive session
// as pending, which is what this replaced.
describe("readRunMode", () => {
  it.each([
    ["an interactive run", { mode: "interactive" }, "interactive"],
    ["a background run", { mode: "background" }, "background"],
    // The backend's own default for a run whose state never carried a mode.
    ["a run with no mode", {}, "background"],
    ["a run with no state at all", undefined, "background"],
    ["a mode that is not a mode", { mode: 7 }, "background"],
  ])("reads %s", (_case, state, expected) => {
    expect(readRunMode(state)).toBe(expected);
  });
});

describe("sidebar action metadata", () => {
  it("preserves creator and run IDs from a full task", () => {
    const task = narrowFullTask({
      id: "task-1",
      title: "Investigate slow startup",
      repository: null,
      created_at: "2026-09-02T09:00:00Z",
      updated_at: "2026-09-02T09:00:00Z",
      created_by: { id: 7 },
      latest_run: {
        id: "run-1",
        status: "in_progress",
        environment: "cloud",
      },
    });

    const result = deriveTaskData(task, {
      session: undefined,
      workspace: undefined,
      timestamp: undefined,
      pinnedIds: new Set(),
      suspendedIds: new Set(),
      slackTaskIds: new Set(),
      slackThreadUrlByTaskId: new Map(),
    });

    expect(result.createdById).toBe(7);
    expect(result.taskRunId).toBe("run-1");
  });
});
