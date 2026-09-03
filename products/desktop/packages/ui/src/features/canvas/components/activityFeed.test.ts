import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import type { SignalReport } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";
import {
  deriveActivityFeedContent,
  filterActivityFeedItems,
  groupActivityItemsByDay,
  markLoadedReadLabel,
  mergeActivityFeedItems,
} from "./activityFeed";

describe("activityFeed", () => {
  it('says "Mark visible as read" while unread activity stays on unloaded pages', () => {
    expect(markLoadedReadLabel(3, 8)).toBe("Mark visible as read");
    expect(markLoadedReadLabel(8, 8)).toBe("Mark all as read");
  });

  it("groups activity by the same local calendar days as the space list", () => {
    const now = new Date(2026, 7, 25, 12);
    const activity = (id: string, day: number, hour: number) => ({
      id,
      activityAt: new Date(2026, 7, day, hour).toISOString(),
    });

    expect(
      groupActivityItemsByDay(
        [
          activity("today-late", 25, 11),
          activity("yesterday", 24, 20),
          activity("today-early", 25, 8),
          activity("last-wednesday", 19, 9),
        ],
        now,
      ).map((group) => [group.label, ...group.items.map((item) => item.id)]),
    ).toEqual([
      ["Today", "today-late", "today-early"],
      ["Yesterday", "yesterday"],
      ["Wednesday", "last-wednesday"],
    ]);
  });

  it("searches task and report content in one activity feed", () => {
    const tasks = [
      {
        id: "task-activity",
        taskId: "task-1",
        taskTitle: "Fix the billing dashboard",
        channelName: "growth",
        snippet: "The chart is empty",
        author: { email: "max@example.com", first_name: "Max" },
        activityAt: "2026-08-25T10:00:00Z",
      } as TaskActivityItem,
    ];
    const reports = [
      {
        id: "report-1",
        title: "Checkout conversion dropped",
        summary: "Mobile customers abandon payment",
        priority: "P3",
        updated_at: "2026-08-25T11:00:00Z",
      } as SignalReport,
    ];
    const feed = mergeActivityFeedItems(tasks, reports);

    expect(
      filterActivityFeedItems(feed, "billing").map((item) => item.id),
    ).toEqual(["task:task-activity"]);
    expect(
      filterActivityFeedItems(feed, "mobile").map((item) => item.id),
    ).toEqual(["report:report-1"]);
    expect(filterActivityFeedItems(feed, "P3").map((item) => item.id)).toEqual([
      "report:report-1",
    ]);
    expect(filterActivityFeedItems(feed, "P1")).toEqual([]);
  });

  it("removes reports and their copy state from unread-only activity", () => {
    const content = deriveActivityFeedContent({
      taskItems: [],
      reports: [
        {
          id: "report-1",
          updated_at: "2026-08-25T11:00:00Z",
        } as SignalReport,
      ],
      totalReportCount: 4,
      mentionsIncluded: true,
      reportsIncluded: true,
      unreadsOnly: true,
    });

    expect(content.feedItems).toEqual([]);
    expect(content.lastShownReportId).toBeNull();
    expect(content.remainingInboxReportCount).toBe(0);
    expect(content.selfDrivingIncluded).toBe(false);
  });
});
