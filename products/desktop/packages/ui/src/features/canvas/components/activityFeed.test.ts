import { describe, expect, it } from "vitest";
import { groupActivityItemsByDay, markLoadedReadLabel } from "./activityFeed";

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
});
