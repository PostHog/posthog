import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { describe, expect, it } from "vitest";
import { getVisibleActivityItems, markLoadedReadLabel } from "./activityFeed";

function item(overrides: Partial<TaskActivityItem>): TaskActivityItem {
  return {
    id: "activity-1",
    taskId: "task-1",
    taskTitle: "Task",
    channelId: null,
    channelName: null,
    activityAt: "2026-08-18T10:00:00Z",
    activityKind: "message",
    snippet: "Update",
    author: null,
    messageId: null,
    isUnread: false,
    ...overrides,
  };
}

describe("activityFeed", () => {
  it('says "Mark visible as read" while unread activity stays on unloaded pages', () => {
    expect(markLoadedReadLabel(3, 8)).toBe("Mark visible as read");
    expect(markLoadedReadLabel(8, 8)).toBe("Mark all as read");
  });

  it.each([
    ["a task created by the current user", item({ activityKind: "created" })],
    [
      "a message from the current user",
      item({
        author: {
          id: 1,
          uuid: "current-user",
          email: "me@example.com",
          first_name: "Me",
        },
      }),
    ],
  ])("hides %s by default", (_name, ownActivity) => {
    const otherActivity = item({ id: "other-activity", taskId: "task-2" });

    expect(
      getVisibleActivityItems([ownActivity, otherActivity], false, 1),
    ).toEqual([otherActivity]);
  });

  it("shows the current user's activity when requested", () => {
    const ownActivity = item({ activityKind: "created" });

    expect(getVisibleActivityItems([ownActivity], true, 1)).toEqual([
      ownActivity,
    ]);
  });

  it("keeps agent and other user activity visible", () => {
    const agentActivity = item({ id: "agent-activity" });
    const otherUserActivity = item({
      id: "other-user-activity",
      author: {
        id: 2,
        uuid: "other-user",
        email: "other@example.com",
        first_name: "Other",
      },
    });

    expect(
      getVisibleActivityItems([agentActivity, otherUserActivity], false, 1),
    ).toEqual([agentActivity, otherUserActivity]);
  });
});
