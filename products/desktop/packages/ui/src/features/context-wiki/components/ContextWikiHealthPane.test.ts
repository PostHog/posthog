import { describe, expect, it } from "vitest";
import { groupFindings } from "./ContextWikiHealthPane";

describe("groupFindings", () => {
  it("groups findings by category for the health tab", () => {
    const findings = [
      { category: "orphan", path: "areas/a.md", message: "No links" },
      { category: "stale", path: "areas/b.md", message: "Old" },
      { category: "orphan", path: "areas/c.md", message: "No links" },
    ];

    expect(groupFindings(findings)).toEqual({
      orphan: [findings[0], findings[2]],
      stale: [findings[1]],
    });
  });
});
