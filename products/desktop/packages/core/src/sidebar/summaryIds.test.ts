import { describe, expect, it } from "vitest";
import { computeSummaryIds } from "./summaryIds";

describe("computeSummaryIds", () => {
  const cases: Array<{
    name: string;
    workspaceIds?: Iterable<string>;
    pinnedTaskIds?: Iterable<string>;
    provisioningTaskIds?: Iterable<string>;
    archivedTaskIds?: Iterable<string>;
    expected: string[];
  }> = [
    {
      name: "unions workspace, pinned, and provisioning ids",
      workspaceIds: ["a", "b"],
      pinnedTaskIds: ["b", "c"],
      provisioningTaskIds: ["d"],
      expected: ["a", "b", "c", "d"],
    },
    {
      name: "removes archived ids from the union",
      workspaceIds: ["a", "b", "c"],
      pinnedTaskIds: ["d"],
      archivedTaskIds: ["b", "d"],
      expected: ["a", "c"],
    },
    {
      name: "deduplicates ids appearing in multiple sources",
      workspaceIds: ["a", "a"],
      pinnedTaskIds: ["a"],
      provisioningTaskIds: ["a"],
      expected: ["a"],
    },
    {
      name: "returns empty array when all inputs are empty",
      expected: [],
    },
    {
      name: "accepts Sets as well as arrays",
      workspaceIds: new Set(["a"]),
      pinnedTaskIds: new Set(["b"]),
      archivedTaskIds: new Set(["a"]),
      expected: ["b"],
    },
  ];

  it.each(cases)("$name", (c) => {
    expect(
      computeSummaryIds({
        workspaceIds: c.workspaceIds ?? [],
        pinnedTaskIds: c.pinnedTaskIds ?? [],
        provisioningTaskIds: c.provisioningTaskIds ?? [],
        archivedTaskIds: c.archivedTaskIds ?? [],
      }).sort(),
    ).toEqual(c.expected.sort());
  });
});
