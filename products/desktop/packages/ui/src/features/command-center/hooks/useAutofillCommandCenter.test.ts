import type { Workspace } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/shell/rendererStorage", () => ({
  electronStorage: {
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  },
}));

const mockUseTasks = vi.hoisted(() => vi.fn());
const mockUseWorkspaces = vi.hoisted(() => vi.fn());
const mockUseArchivedTaskIds = vi.hoisted(() => vi.fn());

vi.mock("../../tasks/useTasks", () => ({
  useTasks: mockUseTasks,
}));

vi.mock("../../workspace/useWorkspace", () => ({
  useWorkspaces: mockUseWorkspaces,
}));

vi.mock("../../archive/useArchivedTaskIds", () => ({
  useArchivedTaskIds: mockUseArchivedTaskIds,
}));

import {
  COMMAND_CENTER_INITIAL_STATE,
  useCommandCenterStore,
} from "../commandCenterStore";
import { useAutofillCommandCenter } from "./useAutofillCommandCenter";

const NOW = new Date("2026-02-27T12:00:00Z").getTime();
const ONE_HOUR_MS = 60 * 60 * 1000;

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: "task-1",
    task_number: 1,
    slug: "task-1",
    title: "Task 1",
    description: "",
    created_at: new Date(NOW).toISOString(),
    updated_at: new Date(NOW).toISOString(),
    origin_product: "code",
    ...overrides,
  };
}

function makeWorkspace(taskId: string): Workspace {
  return {
    taskId,
    folderId: "folder-1",
    folderPath: "/repo",
    mode: "worktree",
    worktreePath: `/repo/${taskId}`,
    worktreeName: taskId,
    branchName: `feat/${taskId}`,
    baseBranch: "main",
    linkedBranch: null,
    createdAt: new Date(NOW).toISOString(),
  };
}

function setQueries(opts: {
  tasks?: Task[];
  workspaces?: Record<string, Workspace>;
  archived?: string[];
  tasksFetched?: boolean;
  workspacesFetched?: boolean;
}) {
  mockUseTasks.mockReturnValue({
    data: opts.tasks ?? [],
    isFetched: opts.tasksFetched ?? true,
  });
  mockUseWorkspaces.mockReturnValue({
    data: opts.workspaces,
    isFetched: opts.workspacesFetched ?? true,
  });
  mockUseArchivedTaskIds.mockReturnValue(new Set(opts.archived ?? []));
}

describe("useAutofillCommandCenter", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    useCommandCenterStore.setState(COMMAND_CENTER_INITIAL_STATE);
    mockUseTasks.mockReset();
    mockUseWorkspaces.mockReset();
    mockUseArchivedTaskIds.mockReset();
  });

  it("does nothing when tasks are not fetched", () => {
    setQueries({ tasksFetched: false, workspaces: {} });
    renderHook(() => useAutofillCommandCenter());
    expect(useCommandCenterStore.getState().cells).toEqual([
      null,
      null,
      null,
      null,
    ]);
  });

  it("does nothing when workspaces are not fetched", () => {
    setQueries({ workspacesFetched: false });
    renderHook(() => useAutofillCommandCenter());
    expect(useCommandCenterStore.getState().cells).toEqual([
      null,
      null,
      null,
      null,
    ]);
  });

  it("does not touch cells when every cell is already populated", () => {
    useCommandCenterStore.setState({ cells: ["a", "b", "c", "d"] });
    setQueries({
      tasks: [makeTask({ id: "t1" })],
      workspaces: { t1: makeWorkspace("t1") },
    });
    renderHook(() => useAutofillCommandCenter());
    expect(useCommandCenterStore.getState().cells).toEqual([
      "a",
      "b",
      "c",
      "d",
    ]);
  });

  it("tops up empty slots and leaves populated ones alone", () => {
    useCommandCenterStore.setState({ cells: ["existing", null, null, null] });
    setQueries({
      tasks: [
        makeTask({ id: "t1", updated_at: new Date(NOW - 100).toISOString() }),
        makeTask({ id: "t2", updated_at: new Date(NOW - 200).toISOString() }),
      ],
      workspaces: { t1: makeWorkspace("t1"), t2: makeWorkspace("t2") },
    });
    renderHook(() => useAutofillCommandCenter());
    expect(useCommandCenterStore.getState().cells).toEqual([
      "existing",
      "t1",
      "t2",
      null,
    ]);
  });

  it("does not fill a task that is already assigned to another cell", () => {
    useCommandCenterStore.setState({ cells: ["t1", null, null, null] });
    setQueries({
      tasks: [
        makeTask({ id: "t1", updated_at: new Date(NOW - 100).toISOString() }),
        makeTask({ id: "t2", updated_at: new Date(NOW - 200).toISOString() }),
      ],
      workspaces: { t1: makeWorkspace("t1"), t2: makeWorkspace("t2") },
    });
    renderHook(() => useAutofillCommandCenter());
    expect(useCommandCenterStore.getState().cells).toEqual([
      "t1",
      "t2",
      null,
      null,
    ]);
  });

  it("fills empty cells with recent tasks that have workspaces", () => {
    setQueries({
      tasks: [
        makeTask({ id: "t1", updated_at: new Date(NOW - 100).toISOString() }),
        makeTask({ id: "t2", updated_at: new Date(NOW - 200).toISOString() }),
      ],
      workspaces: { t1: makeWorkspace("t1"), t2: makeWorkspace("t2") },
    });
    renderHook(() => useAutofillCommandCenter());
    expect(useCommandCenterStore.getState().cells).toEqual([
      "t1",
      "t2",
      null,
      null,
    ]);
  });

  it("skips archived tasks", () => {
    setQueries({
      tasks: [makeTask({ id: "t1" }), makeTask({ id: "t2" })],
      workspaces: { t1: makeWorkspace("t1"), t2: makeWorkspace("t2") },
      archived: ["t1"],
    });
    renderHook(() => useAutofillCommandCenter());
    expect(useCommandCenterStore.getState().cells).toEqual([
      "t2",
      null,
      null,
      null,
    ]);
  });

  it("skips tasks without a workspace", () => {
    setQueries({
      tasks: [makeTask({ id: "t1" }), makeTask({ id: "t2" })],
      workspaces: { t2: makeWorkspace("t2") },
    });
    renderHook(() => useAutofillCommandCenter());
    expect(useCommandCenterStore.getState().cells).toEqual([
      "t2",
      null,
      null,
      null,
    ]);
  });

  it("skips tasks older than the 2 hour window", () => {
    setQueries({
      tasks: [
        makeTask({
          id: "fresh",
          updated_at: new Date(NOW - 100).toISOString(),
        }),
        makeTask({
          id: "stale",
          updated_at: new Date(NOW - 3 * ONE_HOUR_MS).toISOString(),
        }),
      ],
      workspaces: {
        fresh: makeWorkspace("fresh"),
        stale: makeWorkspace("stale"),
      },
    });
    renderHook(() => useAutofillCommandCenter());
    expect(useCommandCenterStore.getState().cells).toEqual([
      "fresh",
      null,
      null,
      null,
    ]);
  });

  it("uses latest_run.updated_at when it is newer than task.updated_at", () => {
    setQueries({
      tasks: [
        makeTask({
          id: "stale",
          updated_at: new Date(NOW - 3 * ONE_HOUR_MS).toISOString(),
          latest_run: {
            id: "run-1",
            task: "stale",
            team: 1,
            branch: null,
            status: "in_progress",
            log_url: "",
            error_message: null,
            output: null,
            state: {},
            created_at: new Date(NOW - 3 * ONE_HOUR_MS).toISOString(),
            updated_at: new Date(NOW - 100).toISOString(),
            completed_at: null,
          },
        }),
      ],
      workspaces: { stale: makeWorkspace("stale") },
    });
    renderHook(() => useAutofillCommandCenter());
    expect(useCommandCenterStore.getState().cells).toEqual([
      "stale",
      null,
      null,
      null,
    ]);
  });

  it("sorts candidates by most recent activity descending", () => {
    setQueries({
      tasks: [
        makeTask({ id: "old", updated_at: new Date(NOW - 1000).toISOString() }),
        makeTask({ id: "new", updated_at: new Date(NOW - 100).toISOString() }),
        makeTask({ id: "mid", updated_at: new Date(NOW - 500).toISOString() }),
      ],
      workspaces: {
        old: makeWorkspace("old"),
        new: makeWorkspace("new"),
        mid: makeWorkspace("mid"),
      },
    });
    renderHook(() => useAutofillCommandCenter());
    expect(useCommandCenterStore.getState().cells).toEqual([
      "new",
      "mid",
      "old",
      null,
    ]);
  });

  it("caps candidates at cells.length", () => {
    setQueries({
      tasks: Array.from({ length: 10 }, (_, i) =>
        makeTask({
          id: `t${i}`,
          updated_at: new Date(NOW - i).toISOString(),
        }),
      ),
      workspaces: Object.fromEntries(
        Array.from({ length: 10 }, (_, i) => [`t${i}`, makeWorkspace(`t${i}`)]),
      ),
    });
    renderHook(() => useAutofillCommandCenter());
    expect(useCommandCenterStore.getState().cells).toEqual([
      "t0",
      "t1",
      "t2",
      "t3",
    ]);
  });

  it("does not change cells when no candidates are available", () => {
    setQueries({ tasks: [], workspaces: {} });
    renderHook(() => useAutofillCommandCenter());
    expect(useCommandCenterStore.getState().cells).toEqual([
      null,
      null,
      null,
      null,
    ]);
  });

  it("leaves hasAutofilled unset when there are no candidates yet", () => {
    setQueries({ tasks: [], workspaces: {} });
    renderHook(() => useAutofillCommandCenter());
    expect(useCommandCenterStore.getState().hasAutofilled).toBe(false);
  });

  it("does not top up empty cells once the grid has been autofilled", () => {
    useCommandCenterStore.setState({
      cells: ["existing", null, null, null],
      hasAutofilled: true,
    });
    setQueries({
      tasks: [
        makeTask({ id: "t1", updated_at: new Date(NOW - 100).toISOString() }),
        makeTask({ id: "t2", updated_at: new Date(NOW - 200).toISOString() }),
      ],
      workspaces: { t1: makeWorkspace("t1"), t2: makeWorkspace("t2") },
    });
    renderHook(() => useAutofillCommandCenter());
    expect(useCommandCenterStore.getState().cells).toEqual([
      "existing",
      null,
      null,
      null,
    ]);
  });

  it("marks autofilled when the grid is already full so removals do not refill", () => {
    useCommandCenterStore.setState({ cells: ["a", "b", "c", "d"] });
    setQueries({
      tasks: [makeTask({ id: "t1" })],
      workspaces: { t1: makeWorkspace("t1") },
    });
    renderHook(() => useAutofillCommandCenter());
    expect(useCommandCenterStore.getState().hasAutofilled).toBe(true);
  });
});
