import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const hoisted = vi.hoisted(() => ({
  togglePin: vi.fn(() => Promise.resolve()),
  archiveTask: vi.fn(() => Promise.resolve()),
  placeTaskInCommandCenter: vi.fn(),
  placeCanvasInCommandCenter: vi.fn(),
}));

vi.mock("@posthog/ui/features/sidebar/usePinnedTasks", () => ({
  usePinnedTasks: () => ({
    pinnedTaskIds: new Set(["canvas-1"]),
    togglePin: hoisted.togglePin,
  }),
}));

vi.mock("@posthog/ui/features/archive/useArchiveTask", () => ({
  useArchiveTask: () => ({ archiveTask: hoisted.archiveTask }),
}));

vi.mock("@posthog/ui/features/command-center/commandCenterStore", () => ({
  useCommandCenterStore: (
    selector: (state: { cells: (string | null)[] }) => unknown,
  ) => selector({ cells: [null] }),
}));

vi.mock("@posthog/ui/features/command-center/placeTaskInCommandCenter", () => ({
  placeTaskInCommandCenter: hoisted.placeTaskInCommandCenter,
  placeCanvasInCommandCenter: hoisted.placeCanvasInCommandCenter,
}));

import { useActivityTaskMenu } from "./useActivityTaskMenu";

function item(overrides: Partial<TaskActivityItem>): TaskActivityItem {
  return {
    id: "activity-1",
    taskId: "task-1",
    taskTitle: "Say hello",
    channelId: "channel-1",
    channelName: null,
    activityAt: "2026-07-27T10:00:00Z",
    activityKind: "mention",
    snippet: "Hello!",
    author: null,
    messageId: null,
    isUnread: true,
    ...overrides,
  };
}

describe("useActivityTaskMenu", () => {
  it("acts on the canvas, not its generating task, for a canvas comment row", () => {
    const { result } = renderHook(() => useActivityTaskMenu());

    const menu = result.current(
      item({
        taskTitle: "Launch canvas",
        commentId: "comment-1",
        commentTarget: { scope: "desktop_canvas", itemId: "canvas-1" },
      }),
    );

    expect(menu).toMatchObject({
      kind: "canvas",
      id: "canvas-1",
      title: "Launch canvas",
      isPinned: true,
      channelId: "channel-1",
    });
    expect(menu.onArchive).toBeUndefined();
    expect(menu.onFile).toBeUndefined();
    menu.onTogglePin();
    expect(hoisted.togglePin).toHaveBeenCalledWith("canvas-1");
    menu.onAddToCommandCenter?.();
    expect(hoisted.placeCanvasInCommandCenter).toHaveBeenCalledWith(
      "canvas-1",
      "Launch canvas",
    );
    expect(hoisted.placeTaskInCommandCenter).not.toHaveBeenCalled();
  });

  it("keeps the task menu for a task row", () => {
    const { result } = renderHook(() => useActivityTaskMenu());

    const menu = result.current(
      item({
        commentId: "comment-1",
        commentTarget: { scope: "task_artifact", itemId: "artifact-1" },
      }),
    );

    expect(menu).toMatchObject({ kind: "task", id: "task-1" });
    expect(menu.onArchive).toBeDefined();
  });
});
