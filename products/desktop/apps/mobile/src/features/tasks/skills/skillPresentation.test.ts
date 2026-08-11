import { describe, expect, it } from "vitest";
import {
  filterSkills,
  skillCategoryLabel,
  skillVersionLabel,
  sortSkillsForDisplay,
} from "./skillPresentation";

describe("skillCategoryLabel", () => {
  it.each<[string | null | undefined, string | null]>([
    ["scout", "Scout"],
    ["code-review", "Code Review"],
    ["data_quality", "Data Quality"],
    ["", null],
    ["   ", null],
    [null, null],
    [undefined, null],
  ])("labels %s as %s", (category, expected) => {
    expect(skillCategoryLabel(category)).toBe(expected);
  });
});

describe("skillVersionLabel", () => {
  it.each<[number, number | null | undefined, string]>([
    [1, 1, "v1"],
    [1, null, "v1"],
    [1, undefined, "v1"],
    [3, 3, "v3 · 3 versions"],
  ])("labels version %s of %s as %s", (version, versionCount, expected) => {
    expect(skillVersionLabel({ version, version_count: versionCount })).toBe(
      expected,
    );
  });
});

describe("filterSkills", () => {
  const skills = [
    { name: "triage-bugs", description: "Sort incoming bug reports" },
    { name: "weekly-digest", description: "Summarize the week" },
  ];

  it.each<[string, string[]]>([
    ["", ["triage-bugs", "weekly-digest"]],
    ["   ", ["triage-bugs", "weekly-digest"]],
    ["TRIAGE", ["triage-bugs"]],
    ["summarize", ["weekly-digest"]],
    ["nothing here", []],
  ])("filters by %s", (query, expected) => {
    expect(filterSkills(skills, query).map((s) => s.name)).toEqual(expected);
  });

  it("does not mutate the input", () => {
    const input = [...skills];
    filterSkills(input, "triage");
    expect(input).toEqual(skills);
  });
});

describe("sortSkillsForDisplay", () => {
  it("sorts alphabetically without mutating the input", () => {
    const input = [{ name: "zebra" }, { name: "alpha" }, { name: "Mango" }];
    expect(sortSkillsForDisplay(input).map((s) => s.name)).toEqual([
      "alpha",
      "Mango",
      "zebra",
    ]);
    expect(input[0].name).toBe("zebra");
  });
});
