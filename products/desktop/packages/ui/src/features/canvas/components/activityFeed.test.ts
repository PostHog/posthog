import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { describe, expect, it } from "vitest";
import {
  activityUnreadTotalForLabel,
  getVisibleActivityItems,
  markLoadedReadLabel,
} from "./activityFeed";

describe("activityFeed", () => {
  it("hides comment activity without hiding existing task mentions", () => {
    const taskMention = {
      id: "task-mention",
      activityKind: "mention",
    } as TaskActivityItem;
    const commentMention = {
      id: "comment-mention",
      activityKind: "mention",
      commentId: "comment-1",
    } as TaskActivityItem;

    expect(
      getVisibleActivityItems([taskMention, commentMention], false),
    ).toEqual([taskMention]);
  });

  it("labels a partial read action as visible only", () => {
    const total = activityUnreadTotalForLabel({
      commentsEnabled: false,
      unreadCount: 8,
      loadedVisibleUnread: 3,
      hasNextPage: true,
    });

    expect(markLoadedReadLabel(3, total)).toBe("Mark visible as read");
  });
});
