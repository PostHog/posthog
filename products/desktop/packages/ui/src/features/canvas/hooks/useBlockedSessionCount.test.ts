import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { describe, expect, it } from "vitest";
import { coldAwaitingInputRows } from "./useBlockedSessionCount";

function item(overrides: Partial<TaskActivityItem>): TaskActivityItem {
  return {
    id: "activity-1",
    taskId: "task-1",
    taskTitle: "Ask a question",
    channelId: "channel-1",
    channelName: "me",
    activityAt: "2026-08-10T00:00:00Z",
    activityKind: "awaiting_input",
    snippet: "",
    author: null,
    messageId: null,
    isUnread: false,
    ...overrides,
  };
}

describe("coldAwaitingInputRows", () => {
  it("takes the tasks whose run stopped for input", () => {
    const ids = coldAwaitingInputRows(
      [
        item({ taskId: "waiting" }),
        item({ taskId: "done", activityKind: "completed" }),
        item({ taskId: "chatty", activityKind: "message" }),
      ],
      new Set(),
    );

    expect(ids.map((row) => row.taskId)).toEqual(["waiting"]);
  });

  // The row records that the agent asked at a moment in time. A mounted session
  // knows whether it is still waiting, and answering a prompt does not write a
  // new activity row — so a row kept over a live session would stay blue after
  // the prompt was answered.
  it("leaves a task to its own session while that session is mounted", () => {
    const ids = coldAwaitingInputRows(
      [item({ taskId: "warm" }), item({ taskId: "cold" })],
      new Set(["warm"]),
    );

    expect(ids.map((row) => row.taskId)).toEqual(["cold"]);
  });
});
