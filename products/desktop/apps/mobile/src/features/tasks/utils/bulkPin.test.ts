import { describe, expect, it } from "vitest";
import { resolveBulkPinTargets } from "./bulkPin";

describe("resolveBulkPinTargets", () => {
  const pinnedSet = new Set(["p1", "p2"]);
  const isPinned = (id: string) => pinnedSet.has(id);

  it("pins every selected task when none are pinned", () => {
    expect(resolveBulkPinTargets(["a", "b"], isPinned)).toEqual({
      targetPinned: true,
      toToggle: ["a", "b"],
    });
  });

  it("unpins every selected task when all are pinned", () => {
    expect(resolveBulkPinTargets(["p1", "p2"], isPinned)).toEqual({
      targetPinned: false,
      toToggle: ["p1", "p2"],
    });
  });

  it("pins only the unpinned tasks in a mixed selection", () => {
    expect(resolveBulkPinTargets(["p1", "a"], isPinned)).toEqual({
      targetPinned: true,
      toToggle: ["a"],
    });
  });

  it("handles an empty selection", () => {
    expect(resolveBulkPinTargets([], isPinned)).toEqual({
      targetPinned: false,
      toToggle: [],
    });
  });
});
