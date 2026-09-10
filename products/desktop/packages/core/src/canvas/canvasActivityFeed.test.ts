import {
  CANVAS_ACTIVITY_FEED_MAX_LIMIT,
  toCanvasActivityFeed,
} from "@posthog/core/canvas/canvasActivityFeed";
import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { describe, expect, it } from "vitest";

function taskItem(overrides: Partial<TaskActivityItem>): TaskActivityItem {
  return {
    id: "activity-1",
    taskId: "task-1",
    taskTitle: "Fix the login redirect",
    channelId: "channel-1",
    channelName: "engineering",
    activityAt: "2026-09-01T10:00:00.000Z",
    activityKind: "message",
    snippet: "Pushed a fix",
    author: null,
    messageId: null,
    isUnread: false,
    ...overrides,
  } as TaskActivityItem;
}

const NO_CANVASES: never[] = [];
const NO_REPORTS: never[] = [];

describe("toCanvasActivityFeed", () => {
  it("interleaves tasks, canvases and reports newest first", () => {
    const snapshot = toCanvasActivityFeed({
      taskItems: [taskItem({ activityAt: "2026-09-01T10:00:00.000Z" })],
      canvases: [
        {
          id: "canvas-1",
          name: "Launch board",
          updatedAt: Date.parse("2026-09-01T11:00:00.000Z"),
          spaceName: "growth",
        },
      ],
      reports: [
        {
          id: "report-1",
          title: "Checkout errors are up",
          summary: "A spike since Monday",
          createdAt: "2026-09-01T09:00:00.000Z",
        },
      ],
    });

    expect(snapshot.rows.map((row) => row.kind)).toEqual([
      "canvas",
      "task",
      "report",
    ]);
  });

  it("carries the id a canvas navigates with, and none for a report", () => {
    const snapshot = toCanvasActivityFeed({
      taskItems: [taskItem({ taskId: "task-9" })],
      canvases: NO_CANVASES,
      reports: [
        {
          id: "report-1",
          title: "Checkout errors are up",
          summary: null,
          createdAt: "2026-09-01T09:00:00.000Z",
        },
      ],
    });

    expect(snapshot.rows.map((row) => row.targetId)).toEqual(["task-9", null]);
  });

  it("counts every unread task update, including the ones the limit dropped", () => {
    const taskItems = Array.from({ length: 4 }, (_, index) =>
      taskItem({
        id: `activity-${index}`,
        taskId: `task-${index}`,
        activityAt: new Date(
          Date.parse("2026-09-01T10:00:00.000Z") + index * 1_000,
        ).toISOString(),
        isUnread: true,
      }),
    );

    const snapshot = toCanvasActivityFeed({
      taskItems,
      canvases: NO_CANVASES,
      reports: NO_REPORTS,
      limit: 2,
    });

    expect(snapshot.rows).toHaveLength(2);
    expect(snapshot.unreadCount).toBe(4);
    expect(snapshot.truncated).toBe(true);
  });

  it("holds the limit a canvas asks for inside the bridge's bound", () => {
    const taskItems = Array.from(
      { length: CANVAS_ACTIVITY_FEED_MAX_LIMIT + 10 },
      (_, index) => taskItem({ id: `activity-${index}` }),
    );

    const snapshot = toCanvasActivityFeed({
      taskItems,
      canvases: NO_CANVASES,
      reports: NO_REPORTS,
      limit: 10_000,
    });

    expect(snapshot.rows).toHaveLength(CANVAS_ACTIVITY_FEED_MAX_LIMIT);
  });
});
