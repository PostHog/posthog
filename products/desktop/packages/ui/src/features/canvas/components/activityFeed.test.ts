import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { describe, expect, it } from "vitest";
import { getVisibleActivityItems } from "./activityFeed";

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
});
