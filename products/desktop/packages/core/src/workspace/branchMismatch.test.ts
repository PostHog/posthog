import { describe, expect, it } from "vitest";
import { isBranchMismatch, shouldWarnBranchMismatch } from "./branchMismatch";

describe("isBranchMismatch", () => {
  it("is false when linked branch is null", () => {
    expect(isBranchMismatch(null, "main")).toBe(false);
  });

  it("is false when current branch is null", () => {
    expect(isBranchMismatch("feat/foo", null)).toBe(false);
  });

  it("is false when branches match", () => {
    expect(isBranchMismatch("feat/foo", "feat/foo")).toBe(false);
  });

  it("is true when branches differ", () => {
    expect(isBranchMismatch("feat/foo", "main")).toBe(true);
  });
});

describe("shouldWarnBranchMismatch", () => {
  it("is true when mismatched and not dismissed", () => {
    expect(shouldWarnBranchMismatch("feat/foo", "main", false)).toBe(true);
  });

  it("is false when dismissed", () => {
    expect(shouldWarnBranchMismatch("feat/foo", "main", true)).toBe(false);
  });

  it("is false when branches match", () => {
    expect(shouldWarnBranchMismatch("feat/foo", "feat/foo", false)).toBe(false);
  });
});
