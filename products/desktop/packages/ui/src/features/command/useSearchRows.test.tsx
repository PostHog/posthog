import type { Task, TaskSearchResult } from "@posthog/shared/domain-types";
import type { CommandSection } from "@posthog/ui/features/command/commandRow";
import { useSearchRows } from "@posthog/ui/features/command/useSearchRows";
import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

function searchResult(
  overrides: Partial<TaskSearchResult> & Pick<TaskSearchResult, "id" | "kind">,
): TaskSearchResult {
  return {
    title: overrides.id,
    subtitle: "",
    task_id: null,
    task_run_id: null,
    channel_id: null,
    updated_at: "2026-09-01T10:00:00Z",
    metadata: {},
    ...overrides,
  };
}

function taskSection(taskIds: string[]): CommandSection {
  return {
    label: "Tasks",
    items: taskIds.map((taskId) => ({
      id: `task-${taskId}`,
      label: `Local ${taskId}`,
      icon: null,
      action: "open-task" as const,
      onRun: () => undefined,
    })),
  };
}

describe("useSearchRows", () => {
  const tasks: Task[] = [];

  function render(
    searchResults: TaskSearchResult[],
    { taskIds = [], bluebirdEnabled = true } = {} as {
      taskIds?: string[];
      bluebirdEnabled?: boolean;
    },
  ) {
    return renderHook(() =>
      useSearchRows({
        remoteQuery: "run",
        searchResults,
        tasks,
        taskSections: taskIds.length > 0 ? [taskSection(taskIds)] : [],
        channels: [{ id: "channel-a", name: "growth" }],
        bluebirdEnabled,
      }),
    ).result.current;
  }

  it("leaves out a task the palette already lists from the local task rows", () => {
    const rows = render(
      [
        searchResult({ id: "a1", kind: "artifact", task_id: "task-b" }),
        searchResult({ id: "t1", kind: "task", task_id: "task-a" }),
      ],
      { taskIds: ["task-a"] },
    );

    expect(rows.map((row) => row.command.id)).toEqual(["search-a1"]);
  });

  it("opens a canvas match in the space it is filed in", () => {
    const rows = render([
      searchResult({
        id: "cv1",
        kind: "canvas",
        title: "Run rate",
        channel_id: "channel-a",
        metadata: { canvas_id: "canvas-1", template_id: "freeform" },
      }),
    ]);

    expect(rows[0].command.label).toBe("Run rate");
    expect(rows[0].command.detail).toBe("#growth");
    expect(rows[0].command.action).toBe("open-canvas");
  });

  it("hides space matches while the spaces feature is off", () => {
    const rows = render(
      [searchResult({ id: "c1", kind: "channel", channel_id: "channel-b" })],
      { bluebirdEnabled: false },
    );

    expect(rows).toEqual([]);
  });

  it("gives every row a place of its own to open in a tab", () => {
    const rows = render([
      searchResult({
        id: "t3",
        kind: "task",
        task_id: "task-d",
        channel_id: "channel-a",
      }),
      searchResult({
        id: "cv2",
        kind: "canvas",
        channel_id: "channel-a",
        metadata: { canvas_id: "canvas-2" },
      }),
      searchResult({ id: "c2", kind: "channel", channel_id: "channel-b" }),
      searchResult({ id: "pr1", kind: "pull_request", task_id: "task-e" }),
    ]);

    expect(rows.map((row) => row.command.href)).toEqual([
      "/spaces/channel-a/tasks/task-d",
      "/spaces/channel-a/dashboards/canvas-2",
      "/spaces/channel-b",
      "/tasks/task-e",
    ]);
  });

  it("leaves a row with no route of its own without an href", () => {
    const rows = render([
      searchResult({ id: "cv3", kind: "canvas", metadata: {} }),
    ]);

    expect(rows[0].command.href).toBeUndefined();
  });

  it("reads a title that arrived with a labeled link as one line", () => {
    const rows = render([
      searchResult({
        id: "t2",
        kind: "task",
        task_id: "task-c",
        title: "why did <https://example.com/runs/1|this run> fail?",
      }),
    ]);

    expect(rows[0].command.label).toBe("why did this run fail?");
  });
});
