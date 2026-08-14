import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { describe, expect, it } from "vitest";
import { getActivityItemsForView, markLoadedReadLabel } from "./activityFeed";

describe("activityFeed", () => {
  it('says "Mark visible as read" while unread activity stays on unloaded pages', () => {
    expect(markLoadedReadLabel(3, 8)).toBe("Mark visible as read");
    expect(markLoadedReadLabel(8, 8)).toBe("Mark all as read");
  });

  it.each([
    ["all", ["created", "mine", "agent", "other"]],
    ["you", ["created", "mine"]],
    ["agent", ["agent"]],
    ["others", ["other"]],
  ] as const)("groups %s activity", (view, expectedIds) => {
    const items = [
      { id: "created", activityKind: "created" },
      {
        id: "mine",
        activityKind: "message",
        author: { email: "me@example.com" },
      },
      { id: "agent", activityKind: "completed" },
      {
        id: "other",
        activityKind: "mention",
        author: { email: "other@example.com" },
      },
    ] as TaskActivityItem[];

    expect(
      getActivityItemsForView(items, view, "me@example.com").map(
        (item) => item.id,
      ),
    ).toEqual(expectedIds);
  });
});
