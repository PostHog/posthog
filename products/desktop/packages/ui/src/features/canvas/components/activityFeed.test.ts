import { describe, expect, it } from "vitest";
import { markLoadedReadLabel } from "./activityFeed";

describe("activityFeed", () => {
  it('says "Mark visible as read" while unread activity stays on unloaded pages', () => {
    expect(markLoadedReadLabel(3, 8)).toBe("Mark visible as read");
    expect(markLoadedReadLabel(8, 8)).toBe("Mark all as read");
  });
});
